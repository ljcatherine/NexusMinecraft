from starlette.responses import JSONResponse
import re


class _UploadTooLarge(Exception):
    pass


class AuthenticationBodyLimit:
    """Bound unauthenticated JSON before FastAPI buffers/parses request bodies."""
    def __init__(self,app,limit=16384):
        self.app,self.limit=app,limit

    async def __call__(self,scope,receive,send):
        if scope['type']!='http' or scope.get('path') not in ('/api/login','/api/invites/redeem') or scope.get('method')!='POST':
            return await self.app(scope,receive,send)
        body=bytearray()
        while True:
            message=await receive()
            if message['type']=='http.disconnect':
                return
            body.extend(message.get('body',b''))
            if len(body)>self.limit:
                return await JSONResponse({'detail':'Authentication request exceeds size limit'},413)(scope,receive,send)
            if not message.get('more_body',False):
                break
        sent=False
        async def replay():
            nonlocal sent
            if not sent:
                sent=True
                return {'type':'http.request','body':bytes(body),'more_body':False}
            return await receive()
        await self.app(scope,replay,send)


class UploadRequestLimit:
    """Reject oversized or unbounded multipart uploads before parsing/spooling."""
    limit = 65 * 1024 * 1024  # 64 MiB file plus bounded multipart overhead

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        upload = (scope['type'] == 'http' and scope.get('method') == 'POST'
                  and re.fullmatch(r'/api/servers/[^/]+/(?:extensions|upload)', scope.get('path', '')))
        if upload:
            headers = {key.lower(): value for key, value in scope.get('headers', [])}
            raw_length = headers.get(b'content-length')
            if raw_length is not None:
                try:
                    length = int(raw_length)
                except ValueError:
                    return await JSONResponse({'detail':'Invalid Content-Length'},400)(scope,receive,send)
                if length < 0 or length > self.limit:
                    return await JSONResponse({'detail':'Upload request exceeds size limit'},413)(scope,receive,send)
            total = 0
            async def bounded_receive():
                nonlocal total
                message = await receive()
                if message['type'] == 'http.request':
                    total += len(message.get('body', b''))
                    if total > self.limit:
                        raise _UploadTooLarge
                return message
            try:
                await self.app(scope, bounded_receive, send)
            except _UploadTooLarge:
                return await JSONResponse({'detail':'Upload request exceeds size limit'},413)(scope,receive,send)
            return
        await self.app(scope, receive, send)
