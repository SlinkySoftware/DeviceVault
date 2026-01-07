"""
DeviceVault - A comprehensive network device backup management application with web interface for user and admin access and backend component for automated backup collection.
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
from git import Repo
class GitStorage:
    def __init__(self, repo_path):
        self.repo_path = repo_path
        if not os.path.exists(repo_path): Repo.init(repo_path)
        self.repo = Repo(repo_path)
    def save(self, rel_path, content):
        full = os.path.join(self.repo_path, rel_path); os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full,'w') as f: f.write(content)
        self.repo.index.add([full]); self.repo.index.commit(f"devicevault: save {rel_path}")
        return full
