"""CI-only synthetic check: health, non-root storage, restart and encrypted backup.

Creates and removes only a uniquely named test container/volume. No real OIDC
credentials, account statements or provider calls are used.
"""

import json
import os
import subprocess
import sys
import time
import urllib.request
from uuid import uuid4


def run(*arguments, env=None):
    return subprocess.check_output(["docker", *arguments], text=True, env=env).strip()


def main():
    image = sys.argv[1]
    name = "sig-smoke-" + uuid4().hex
    volume = name + "-data"
    marker = uuid4().hex
    key = run(
        "run",
        "--rm",
        image,
        "python",
        "-c",
        "from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())",
    )
    config = f'''[auth]
redirect_uri = "https://synthetic.invalid/oauth2callback"
cookie_secret = "synthetic-cookie-secret-for-container-test-only"
client_id = "synthetic-client"
client_secret = "synthetic-secret"
server_metadata_url = "https://synthetic.invalid/.well-known/openid-configuration"
[[access.identities]]
issuer = "https://synthetic.invalid"
subject = "synthetic-admin"
role = "ADMIN"
[workspace]
enabled = true
database_path = "/var/data/cases.db"
encryption_key = "{key}"
[technical_watchlist]
backend = "sqlite"
database_path = "/var/data/technical.db"
'''
    environment = {**os.environ, "SIG_SECRETS_TOML": config}

    def health():
        port = run("port", name, "8501/tcp").split(":")[-1]
        for _ in range(45):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/_stcore/health", timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:
                pass
            time.sleep(1)
        raise RuntimeError("Synthetic container did not become healthy.")

    common = """
import tomllib
from pathlib import Path
from case_workspace import CaseStore, Principal
c=tomllib.loads(Path('.streamlit/secrets.toml').read_text())['workspace']
s=CaseStore(Path(c['database_path']), c['encryption_key'].encode())
p=Principal('https://synthetic.invalid','synthetic-admin','ADMIN')
"""
    try:
        run("volume", "create", volume)
        run(
            "run",
            "-d",
            "--name",
            name,
            "-e",
            "SIG_SECRETS_TOML",
            "-v",
            volume + ":/var/data",
            "-p",
            "127.0.0.1::8501",
            image,
            env=environment,
        )
        health()
        assert run("exec", name, "id", "-u") == "10001"
        prepare = (
            common
            + f"""
s.initialize(p)
state=s.create(p,'Synthetic CI')
state=s.update(p,state['id'],state['revision'],'account',
    {{'broker':'GBM','product':'Trading MX','portfolio':'SIM','currency':'MXN'}})
s.save_working(p,state['id'],state['accounts'][0]['id'],'draft','analysis',{{'marker':'{marker}'}})
"""
        )
        run("exec", name, "python", "-c", prepare)
        run("restart", name)
        health()
        verify = (
            common
            + f"""
from operational_backup import create_backup_bundle, verify_backup_bundle
state=s.read(p,s.list_cases(p)[0]['id'])
assert s.working_records(p,state['id'],state['accounts'][0]['id'],'draft')[0]['data']['marker']=='{marker}'
backup=Path('/var/data/test.sigbackup')
assert create_backup_bundle(s,p,backup)['integrity']=='VERIFIED'
assert verify_backup_bundle(s,p,backup,restore_to=Path('/var/data/recovered'))['integrity']=='VERIFIED'
print('synthetic_restart_and_backup=PASS')
"""
        )
        result = run("exec", name, "python", "-c", verify)
        print(json.dumps({"health": True, "non_root": True, "restart_and_backup": "PASS" in result}))
    finally:
        # Names are generated here; never accept a user-supplied container/volume for cleanup.
        subprocess.run(["docker", "rm", "--force", name], check=False, capture_output=True)
        subprocess.run(["docker", "volume", "rm", volume], check=False, capture_output=True)


if __name__ == "__main__":
    main()
