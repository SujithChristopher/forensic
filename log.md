# Check status
  sudo systemctl status data-recorder.service

  # View logs (live)
  sudo journalctl -u data-recorder.service -f

  # View recent logs
  sudo journalctl -u data-recorder.service --lines 50

  # Stop the service
  sudo systemctl stop data-recorder.service

  # Start the service
  sudo systemctl start data-recorder.service

  # Restart the service
  sudo systemctl restart data-recorder.service