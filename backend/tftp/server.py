"""
TFTP receiver server helper for DeviceVault.

Copyright (C) 2026, Slinky Software

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import os
from tftpy import TftpServer
if __name__=='__main__':
    base = os.environ.get('DEVICEVAULT_TFTP_DIR','tftp_incoming'); os.makedirs(base, exist_ok=True)
    TftpServer(base).listen('0.0.0.0',69)
