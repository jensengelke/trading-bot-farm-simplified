import os
import shutil
import re

src_dir = r"c:\git\trading-bot-farm\src"
dest_dir = r"c:\git\trading-bot-farm-simplified\src"

# 1. Copy db folder
db_src = os.path.join(src_dir, 'db')
db_dest = os.path.join(dest_dir, 'db')
os.makedirs(db_dest, exist_ok=True)

for file in ['database.py', 'models.py', 'repository.py']:
    shutil.copy2(os.path.join(db_src, file), os.path.join(db_dest, file))

# 2. Copy services/flex_query_service.py
services_src = os.path.join(src_dir, 'services')
services_dest = os.path.join(dest_dir, 'services')
os.makedirs(services_dest, exist_ok=True)

shutil.copy2(os.path.join(services_src, 'flex_query_service.py'), os.path.join(services_dest, 'flex_query_service.py'))

# 3. Read sync_manager.py, adjust it, and write it
with open(os.path.join(services_src, 'sync_manager.py'), 'r', encoding='utf-8') as f:
    sync_content = f.read()

# Adjust imports: remove config_loader, add yaml
sync_content = re.sub(
    r'from ..config_loader import .*?\n',
    'import yaml\nimport os\n\ndef load_config(filepath=".config.yaml") -> dict:\n    if not os.path.exists(filepath):\n        return {}\n    with open(filepath, "r") as f:\n        return yaml.safe_load(f)\n',
    sync_content
)

# Adjust init
sync_content = re.sub(
    r'self\.config = load_private_config\(\)',
    'self.config = load_config()',
    sync_content
)

# Adjust sync_account (account config parsing)
# In simplified, flex_token and flex_query_id will be under 'flex' in .config.yaml
# We also just want to get it for the specified account, but .config.yaml structure is different.
sync_content = re.sub(
    r'accounts = self\.config\.get\("accounts", \[\]\).*?query_id = acct_conf\.get\("flex_query_id"\)',
    'flex_conf = self.config.get("flex", {})\n            token = flex_conf.get("flex_token")\n            query_id = flex_conf.get("flex_query_id")',
    sync_content,
    flags=re.DOTALL
)

# Remove overrides and ignored refs logic, as it's not needed yet according to requirements
sync_content = re.sub(
    r'# Apply overrides first.*?ignored_refs = settings\.get\("shadow_accounting", \{\}\)\.get\("ignored_order_refs", \[\]\)',
    'ignored_refs = []',
    sync_content,
    flags=re.DOTALL
)

with open(os.path.join(services_dest, 'sync_manager.py'), 'w', encoding='utf-8') as f:
    f.write(sync_content)

print("Files copied and sync_manager.py adjusted successfully.")
