# Network Copy v2.0 - Raspberry Pi File Transfer Application

A comprehensive GUI application for transferring files from Raspberry Pi devices to local machines via SFTP, with advanced features including file preview, device profile management, and transfer history.

## Features

### Core Features
- **File Transfer via SFTP** - Securely transfer files from Raspberry Pi to local machine
- **File Preview** - Preview files before transfer with size information and new/existing status
- **Device Profiles** - Save and manage multiple Raspberry Pi device configurations
- **Network Scanning** - Automatically discover Raspberry Pi devices on the network
- **File Deletion** - Optional automatic deletion of files after successful transfer
- **Directory Structure Preservation** - Maintains remote directory structure locally
- **Transfer History** - Track all transfers with statistics and metrics

### Device Profile Management
- Save multiple device configurations with encrypted passwords
- Quick switching between devices
- Per-device transfer statistics
- Test connection functionality
- Profile duplication for easy setup

### User Interface
- **Intuitive Main Window** with profile selection and directory settings
- **File Preview Dialog** showing file list, sizes, and transfer status
- **Profile Management Dialog** for creating and editing device profiles
- **Settings Dialog** for application preferences
- **Real-time Progress** bars and status updates
- **Transfer Log** with timestamps and detailed messages

### Advanced Features
- **Auto-date Folders** - Organize transfers into date-based subfolders
- **Settings Persistence** - Application state and preferences automatically saved
- **Encryption** - Passwords encrypted using Fernet symmetric encryption
- **SQLite History** - Efficient transfer history tracking and statistics
- **Migration** - Automatic migration from legacy settings.txt format

## Architecture

### Directory Structure

```
netcpy/
├── main.py                          # Application entry point
├── models/                          # Data classes
│   ├── device_profile.py            # DeviceProfile model
│   ├── transfer_record.py           # TransferRecord model
│   └── file_info.py                 # FileInfo model
├── core/                            # Business logic
│   ├── settings_manager.py          # Settings persistence & migration
│   ├── profile_manager.py           # Device profile management
│   ├── transfer_history.py          # Transfer history (SQLite)
│   └── file_analyzer.py             # File analysis for preview
├── workers/                         # Background threads
│   ├── network_scanner.py           # Network device discovery
│   ├── file_preview_worker.py       # File preview analysis
│   ├── sftp_worker.py               # SFTP file transfer
│   └── file_deleter.py              # Remote file deletion
├── ui/                              # User interface
│   ├── main_window.py               # Main application window
│   ├── dialogs/                     # Dialog windows
│   │   ├── preview_dialog.py        # File preview dialog
│   │   ├── profile_dialog.py        # Profile management dialog
│   │   └── settings_dialog.py       # Settings dialog
│   └── widgets/                     # UI widgets (extensible)
└── utils/                           # Utility functions
    ├── formatters.py                # File size, duration formatting
    └── validators.py                # Input validation
```

### Key Classes

**Data Models** (`models/`)
- `DeviceProfile` - Stores device connection info and statistics
- `TransferRecord` - Tracks individual transfer operations
- `FileInfo` - Represents a file for preview

**Core Logic** (`core/`)
- `SettingsManager` - JSON-based settings with legacy migration
- `ProfileManager` - Device profile CRUD with encryption
- `TransferHistory` - SQLite database for transfer records
- `FileAnalyzer` - Remote file discovery and comparison

**Workers** (`workers/`) - All inherit from QThread
- `NetworkScanner` - Multi-threaded network scanning
- `FilePreviewWorker` - Background file analysis
- `SftpWorker` - File transfer with optional deletion
- `FileDeleter` - Remote file deletion

**UI** (`ui/`)
- `MainWindow` - Main application window
- `PreviewDialog` - File selection before transfer
- `ProfileDialog` - Device profile management
- `SettingsDialog` - Application settings

## Running the Application

### Requirements
- Python 3.8+
- PySide6
- paramiko
- cryptography

### Installation

```bash
# Install dependencies
pip install PySide6 paramiko cryptography

# Run the application
python -m netcpy.main

# Or as a module
python -c "from netcpy.main import main; main()"
```

### Basic Workflow

1. **Configure Device Profile**
   - Click "Manage" → "New" to create a profile
   - Enter Raspberry Pi hostname/IP, username, password
   - Test connection to verify
   - Save profile

2. **Select Directory**
   - Choose remote directory (e.g., `/home/pi/data`)
   - Browse and select local directory

3. **Preview Files**
   - Click "Preview Files" button
   - Review file list and sizes
   - Select files to transfer (or deselect existing files)
   - Click "Start Transfer"

4. **Transfer Complete**
   - Monitor progress in log and progress bar
   - Files automatically organized in local directory structure
   - Transfer recorded in history

## Configuration

### Settings File Locations

- **Settings**: `~/.rpi_transfer/settings.json`
- **Profiles**: `~/.rpi_transfer/profiles.json`
- **History**: `~/.rpi_transfer/history.db`
- **Encryption Key**: `~/.rpi_transfer/.key`

### Settings Options

**General**
- Auto-date folder: Create `YYYY-MM-DD` subfolder for transfers
- Auto-scan on startup: Automatically scan network when starting

**Network**
- Default network range for scanning (CIDR notation)

**Transfer**
- History retention period (days)

## New Features in v2.0

### 1. File Preview
- **New Dialog**: Preview files before transfer
- **Smart Status**: Shows "New" (green) for new files, "Existing" (gray) for unchanged
- **Size Information**: Displays file sizes in human-readable format
- **Filtering**: Option to show only new files
- **Selection**: Select/deselect individual files for transfer

### 2. Device Profile Management
- **Multiple Profiles**: Save unlimited device configurations
- **Encrypted Storage**: Passwords encrypted with Fernet
- **Quick Switch**: Dropdown to switch between profiles
- **Statistics**: Per-profile transfer statistics
- **Test Connection**: Verify credentials before saving

### 3. Modular Architecture
- **Separated Concerns**: Clear split between business logic, UI, and workers
- **Testability**: Independent modules can be tested in isolation
- **Extensibility**: Easy to add new features (dashboard, scheduled transfers, etc.)
- **Maintainability**: Well-organized file structure and clear responsibilities

### 4. Settings Migration
- **Automatic**: Old `settings.txt` automatically converted to new format
- **Backward Compatible**: Existing settings preserved
- **Encryption**: Legacy passwords require re-entry for security

### 5. Transfer History
- **SQLite Database**: Efficient storage and querying
- **Statistics**: Total files, data transferred, average duration
- **Organization**: Organized by date and device profile
- **Cleanup**: Old records automatically removed after 90 days

## Development & Extension

### Adding a New Feature

1. **Add Model Class** (if needed) in `models/`
2. **Add Business Logic** in `core/` or `workers/`
3. **Add UI Component** in `ui/dialogs/` or `ui/widgets/`
4. **Wire Up** in MainWindow or relevant dialog

### Testing

Each component can be tested independently:
- Models: Direct instantiation and validation
- Managers: Mock file I/O
- Workers: Mock SFTP connections
- Dialogs: Manual UI testing

## Troubleshooting

### Connection Failed
- Verify hostname/IP is reachable
- Check SSH credentials
- Ensure port 22 is open
- Use "Test Connection" button in Profile dialog

### Preview Shows No Files
- Verify remote directory path is correct
- Check directory exists and contains files
- Verify SSH user has read permissions

### Settings Not Saving
- Check `~/.rpi_transfer/` directory is writable
- Verify no file permission issues
- Check application has write access to home directory

## Migration from v1.x

1. **Automatic Migration**: First run detects old `settings.txt`
2. **Profile Creation**: Old settings converted to first device profile
3. **Password Re-entry**: Must re-enter password for security (not auto-migrated)
4. **Backup**: Old settings saved as `settings.txt.backup`

## Future Enhancements

- Dashboard with transfer statistics and recent history
- Scheduled/automated transfers
- Cloud storage support (S3, Google Drive)
- Concurrent transfers from multiple devices
- Transfer templates and presets
- Command-line interface for automation
- Email notifications on transfer completion

## Version History

### v2.0
- Complete architectural redesign
- File preview functionality
- Device profile management
- Settings migration
- Transfer history tracking
- Modular code organization

### v1.x
- Basic SFTP file transfer
- Simple GUI with inline settings
- Network scanning
- File deletion option

## License

© 2026 Forensic System

## Support

For issues or feature requests, refer to the project documentation or contact the development team.
