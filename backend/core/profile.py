import os
import logging
logger = logging.getLogger("profile")

class Profile:
    def __init__(self, name="default", base_dir=None):
        self.name = name
        # If a base directory is not provided, use the current working directory.
        if base_dir is None:
            base_dir = os.getcwd()
        self.base_dir = base_dir
        logger.info("Profile: init name=%s base_dir=%s", name, base_dir)
        # Define paths relative to the base directory and profile name.
        self.wordlist_path = os.path.join(base_dir, name,  f"word-index.tsv")
        self.ledger_path = os.path.join(base_dir, name, f"ledger.tsv")
        self.batches_dir = os.path.join(base_dir, name, "batches")
        self.ui_log_path = os.path.join(base_dir, name, "ui-log.tsv")
        self.reminders_path = os.path.join(base_dir, name, "reminders.tsv")
        self.datasets_dir = os.path.join(base_dir, name, "datasets")
        self.models_dir = os.path.join(base_dir, name, "models", "tokenizer")
        os.makedirs(os.path.dirname(self.ui_log_path), exist_ok=True)
        # Ensure the parent directories exist.
        os.makedirs(os.path.dirname(self.wordlist_path), exist_ok=True)
        os.makedirs(os.path.dirname(self.ledger_path), exist_ok=True)
        os.makedirs(self.batches_dir, exist_ok=True)
        os.makedirs(self.datasets_dir, exist_ok=True)
        os.makedirs(self.models_dir, exist_ok=True)
        logger.info(
            "Profile: paths wordlist=%s ledger=%s batches=%s ui_log=%s reminders=%s datasets=%s models=%s",
            self.wordlist_path, self.ledger_path, self.batches_dir, self.ui_log_path,
            self.reminders_path, self.datasets_dir, self.models_dir
        )

# Provide a default profile instance.
default_profile = Profile()
