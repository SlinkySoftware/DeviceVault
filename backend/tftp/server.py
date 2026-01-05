
import os
from tftpy import TftpServer
if __name__=='__main__':
    base = os.environ.get('DEVICEVAULT_TFTP_DIR','tftp_incoming'); os.makedirs(base, exist_ok=True)
    TftpServer(base).listen('0.0.0.0',69)
