## Instructions on how to run the above script for startup

Note that fileserver.service runs the file service automatically on startup of the device.

```shell
sudo nano /etc/systemd/system/fileserver.service
```

Copy and paste the fileserver.service file and replace the <user-name>

```shell
sudo systemctl enable fileserver
sudo systemctl start fileserver
```

Check status of the script

```shell
sudo systemctl status fileserver
```