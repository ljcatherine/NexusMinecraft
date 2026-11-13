import argparse
import getpass
import json
import os
from pathlib import Path
from .auth import Auth


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['user','rename','invite','accounts'])
    parser.add_argument('username',nargs='?')
    parser.add_argument('new_username',nargs='?')
    parser.add_argument('--role', choices=['admin','viewer'], default='admin')
    parser.add_argument('--config', default=os.environ.get('PS5_PANEL_CONFIG','/etc/ps5-panel/config.json'))
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    Path(config['data']).mkdir(parents=True, exist_ok=True)
    auth = Auth(Path(config['data'])/'panel.sqlite3')
    if args.command == 'accounts':
        print(json.dumps(auth.accounts(),indent=2))
        return
    if not args.username:
        parser.error('username is required')
    if args.command == 'rename':
        if not args.new_username:
            parser.error('new_username is required')
        auth.rename(args.username,args.new_username)
        print('Account renamed; password preserved, old sessions revoked.')
        return
    if args.command == 'invite':
        token = auth.invite(args.username,args.role,'local-cli')
        print(args.username+' ('+args.role+'): '+config['origin']+'/#invite='+token)
        print('Private one-use invitation; expires in 24 hours. Share only with its intended recipient.')
        return
    password = getpass.getpass('Password (minimum 12 characters): ')
    if password != getpass.getpass('Confirm password: '):
        raise SystemExit('Passwords do not match')
    auth.user(args.username, password, args.role)
    print('User saved; existing sessions revoked.')


if __name__ == '__main__':
    main()
