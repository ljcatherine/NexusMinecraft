#!/usr/bin/python3 -I
import subprocess

exists = subprocess.run(['/usr/sbin/nft','list','table','inet','ps5_panel_rcon'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL).returncode == 0
rules = ('delete table inet ps5_panel_rcon\n' if exists else '') + '''table inet ps5_panel_rcon {
 chain input {
  type filter hook input priority -10; policy accept;
  iifname != "lo" tcp dport { 25575, 25576 } drop
 }
}
'''
subprocess.run(['/usr/sbin/nft','-f','-'],input=rules,text=True,check=True)
