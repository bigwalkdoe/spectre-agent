# Linux Hardening Reference

Key files and commands Spectre Agent inspects:

- `/etc/ssh/sshd_config` — `PermitRootLogin`, `PasswordAuthentication`
- `/etc/apt/apt.conf.d/20auto-upgrades` or `/etc/dnf/automatic.conf` — unattended updates
- `/etc/security/limits.conf` — `core` dumps
- `/etc/grub.d/00_header` or `/boot/grub2/grub.cfg` — boot password
- `ufw` / `nft list ruleset` / `iptables -L` — host firewall
- `ss -tuln` — listening sockets
- `/var/log/auth.log`, `/var/log/secure`, `journalctl -u sshd` — auth events
