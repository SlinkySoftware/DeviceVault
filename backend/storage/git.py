
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
