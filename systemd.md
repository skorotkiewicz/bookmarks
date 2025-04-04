# Setting Up a Python Application as a systemd Service

This guide walks through the process of configuring a Python application to run as a systemd service, allowing it to start automatically on boot and be managed easily.

## Step 1: Create a Dedicated User Account

First, create a dedicated user for your application:

```bash
sudo useradd -m -s /bin/bash username
```

This creates a new user with:
- `-m`: Home directory at `/home/username`
- `-s /bin/bash`: Bash as the login shell

## Step 2: Create a systemd User Service File

As the application user, create the systemd service configuration:

```bash
mkdir -p ~/.config/systemd/user/
nano ~/.config/systemd/user/your-app-name.service
```

Add the following content to the service file:

```ini
[Unit]
Description=Your Python Application Description
After=network.target

[Service]
WorkingDirectory=/home/username/your-app-directory
ExecStart=/home/username/your-app-directory/venv/bin/python /home/username/your-app-directory/app.py
Environment=PYTHONUNBUFFERED=1
Restart=on-failure
RestartSec=5s
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=default.target
```

### Example Configuration

Here's an example for a bookmarks management application:

```ini
[Unit]
Description=Lightweight web application for organizing, storing, and managing your bookmarks
After=network.target

[Service]
WorkingDirectory=/home/username/bookmarks
ExecStart=/home/username/bookmarks/venv/bin/python /home/username/bookmarks/app.py
Restart=on-failure
TimeoutStopSec=5

[Install]
WantedBy=default.target
```

## Step 3: Enable User Lingering

To ensure the user's services start on boot (even without login), enable lingering for the user:

```bash
sudo loginctl enable-linger username
```

## Step 4: Configure D-Bus for the User Session

Add the following line to the user's `.bashrc` file:

```bash
echo 'export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$UID/bus' >> /home/username/.bashrc
```

Source the updated file:

```bash
source /home/username/.bashrc
```

## Step 5: Manage the Service

Now the user can manage their service with the following commands:

```bash
# Reload daemons
systemctl --user daemon-reload

# Enable the service to start on boot
systemctl --user enable your-app-name.service

# Start the service immediately
systemctl --user start your-app-name.service

# Check service status
systemctl --user status your-app-name.service

# Stop the service
systemctl --user stop your-app-name.service

# Disable the service from starting on boot
systemctl --user disable your-app-name.service

# View service logs
journalctl --user -u your-app-name.service
```

## Step 6: Testing the Setup

Verify everything works by:

1. Starting the service: `systemctl --user start your-app-name.service`
2. Checking its status: `systemctl --user status your-app-name.service`
3. Rebooting the system to ensure it starts automatically

## Common Issues and Solutions

- **Service not starting on boot**: Verify lingering is enabled with `loginctl show-user username | grep Linger`
- **Permission problems**: Ensure proper ownership with `chown -R username:username /home/username/your-app-directory`
- **Path errors**: Confirm all paths in the service file are absolute and correct
