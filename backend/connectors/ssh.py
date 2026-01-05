
import paramiko
class SSHConnector:
    def __init__(self, command='show running-config'):
        self.command = command
    def fetch_config(self, device, credential):
        client = paramiko.SSHClient(); client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(hostname=device.ip_address, username=credential.data.get('username'), password=credential.data.get('password'), look_for_keys=False)
        _, stdout, _ = client.exec_command(self.command)
        text = stdout.read().decode('utf-8', errors='ignore'); client.close(); return text
