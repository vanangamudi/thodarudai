import os

class Profile:
    def __init__(self, name="default", base_dir=None):
        self.name = name
        # If a base directory is not provided, use the current working directory.
        if base_dir is None:
            base_dir = os.getcwd()
        self.base_dir = base_dir
        # Define paths relative to the base directory and profile name.
        self.wordlist_path = os.path.join(base_dir, name,  f"word-index.tsv")
        self.ledger_path = os.path.join(base_dir, name, f"ledger.tsv")
        self.batches_dir = os.path.join(base_dir, name, "batches")
        # Ensure the parent directories exist.
        os.makedirs(os.path.dirname(self.wordlist_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        os.makedirs(self.batches_dir, exist_ok=True)

# Provide a default profile instance.
default_profile = Profile()
