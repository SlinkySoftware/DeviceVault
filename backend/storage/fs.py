
import os
class FileSystemStorage:
    def __init__(self, base_path):
        self.base_path = base_path; os.makedirs(base_path, exist_ok=True)
    def save(self, rel_path, content):
        full = os.path.join(self.base_path, rel_path); os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full,'w') as f: f.write(content)
        return full
