# AI Lab Quickstart — Ubuntu 26.04

```bash
# Install snaps
sudo snap install lxd
sudo snap install lemonade-server --channel edge

# Initialise LXD
sudo lxd init --auto

# Add your user to the lxd group (log out and back in after this)
sudo usermod -aG lxd $USER
newgrp lxd

# Install the locally built ailab snap
sudo snap install --dangerous ailab_*.snap

# Connect the LXD interface
sudo snap connect ailab:lxd lxd:lxd

# Open the web UI
xdg-open http://127.0.0.1:11500
```
