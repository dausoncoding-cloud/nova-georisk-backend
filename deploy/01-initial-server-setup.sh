#!/usr/bin/env bash
#
# Run ONCE, as root, right after the Linode is provisioned:
#   ssh root@your.linode.ip 'bash -s' < deploy/01-initial-server-setup.sh -- deploy your-ssh-public-key.pub
# or copy it up and run interactively.
#
# Creates a non-root sudo user, installs your SSH key for it, disables
# root/password SSH login, and enables ufw with only SSH/HTTP/HTTPS open.

set -euo pipefail

NEW_USER="${1:-deploy}"
PUBKEY_FILE="${2:-}"

if [ "$(id -u)" -ne 0 ]; then
  echo "Run this as root." >&2
  exit 1
fi

echo "### Updating packages ..."
apt-get update -y && apt-get upgrade -y

echo "### Creating user '$NEW_USER' ..."
if ! id "$NEW_USER" &>/dev/null; then
  adduser --disabled-password --gecos "" "$NEW_USER"
  usermod -aG sudo "$NEW_USER"
fi

mkdir -p "/home/$NEW_USER/.ssh"
if [ -n "$PUBKEY_FILE" ] && [ -f "$PUBKEY_FILE" ]; then
  cat "$PUBKEY_FILE" >> "/home/$NEW_USER/.ssh/authorized_keys"
elif [ -f /root/.ssh/authorized_keys ]; then
  # Fall back to whatever key(s) got root in, so you don't lock yourself out.
  cat /root/.ssh/authorized_keys >> "/home/$NEW_USER/.ssh/authorized_keys"
fi
chmod 700 "/home/$NEW_USER/.ssh"
chmod 600 "/home/$NEW_USER/.ssh/authorized_keys"
chown -R "$NEW_USER:$NEW_USER" "/home/$NEW_USER/.ssh"

echo "### Hardening SSH ..."
sed -i 's/^#\?PermitRootLogin.*/PermitRootLogin no/' /etc/ssh/sshd_config
sed -i 's/^#\?PasswordAuthentication.*/PasswordAuthentication no/' /etc/ssh/sshd_config
systemctl restart sshd

echo "### Configuring firewall (ufw) ..."
apt-get install -y ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "### Done."
echo "### Verify you can log in as '$NEW_USER' in a NEW terminal before closing this session:"
echo "###   ssh $NEW_USER@$(curl -s ifconfig.me)"
echo "### Once confirmed, continue with deploy/02-deploy-app.sh as '$NEW_USER'."
