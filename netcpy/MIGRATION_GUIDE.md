# Migration Guide: Network Copy v1.x → v2.0

This guide helps users transition from the old single-file application to the new modular v2.0 architecture.

## What's New

Network Copy v2.0 is a complete rewrite with significant improvements:

- **Modular Architecture** - Code organized into packages (models, core, workers, ui, utils)
- **File Preview** - See files before transfer, select which ones to transfer
- **Device Profiles** - Save multiple Raspberry Pi configurations
- **Transfer History** - Track all transfers with statistics
- **Encrypted Passwords** - Passwords now encrypted in storage
- **Better Settings** - JSON-based settings with persistent window state
- **Professional UI** - Improved dialogs and workflow

## Automatic Migration

The new application automatically detects your old settings and migrates them:

1. First run checks for `~/.rpi_transfer/settings.txt`
2. Old settings are converted to new JSON format
3. A default device profile is created from your settings
4. Original file is backed up as `settings.txt.backup`

## What Changes

### Old Workflow
```
1. Start app
2. Enter hostname, username, password in main window
3. Enter directories
4. Click "Start Transfer"
→ All files transferred (no preview or selection)
```

### New Workflow
```
1. Start app
2. Create device profile (once) with connection details
3. Enter directories
4. Click "Preview Files" to see what will be transferred
5. Select files to transfer (can skip existing files)
6. Click "Start Transfer"
→ Only selected files transferred
```

## File Migration

### Settings & Data Migration

**Old Format**
- Settings file: `~/.rpi_transfer/settings.txt` (plain text key=value)
- No password encryption, plaintext storage
- No transfer history
- Window state not saved

**New Format**
- Settings: `~/.rpi_transfer/settings.json` (structured JSON)
- Profiles: `~/.rpi_transfer/profiles.json` (encrypted passwords)
- History: `~/.rpi_transfer/history.db` (SQLite)
- Encryption Key: `~/.rpi_transfer/.key` (symmetric Fernet key)
- Backup: `~/.rpi_transfer/settings.txt.backup` (your old settings)

### Data Loss Prevention

**Nothing is deleted:**
- Old settings backed up to `settings.txt.backup`
- New files created alongside old ones
- You can manually restore old settings if needed
- All your transfer history is preserved in new format

## First Run

1. **Install v2.0**
   ```bash
   pip install --upgrade netcpy
   ```

2. **First Launch**
   - App detects old settings
   - Automatically creates new format files
   - Creates first device profile from old settings
   - Shows message about migration

3. **Verify Migration**
   - Check that device profile was created
   - Verify settings in "Settings" dialog
   - **Important**: Re-enter password (for security)
   - Test connection in Profile dialog

## Re-entering Passwords

**Why passwords aren't auto-migrated:**
- Old version stored passwords in plaintext
- New version uses encryption (more secure)
- Asking you to re-enter ensures you approve the new storage method
- Prevents accidental password exposure

**Steps:**
1. Open Profile dialog ("Manage" button)
2. Click profile to select it
3. Clear password field and re-enter password
4. Click "Test Connection" to verify
5. Click "Save"

## New Features to Explore

### File Preview
```
Before Transfer:
1. Select device profile
2. Click "Preview Files"
3. Dialog shows all files with sizes
4. Files marked as "New" (green) or "Existing" (gray)
5. Select which files to transfer
6. Only selected files transferred
```

### Device Profiles
```
Save Multiple Devices:
1. Create profile for Lab Pi (10.0.0.5)
2. Create profile for Field Pi (10.0.0.10)
3. Switch between them with dropdown
4. Each has separate transfer history
```

### Transfer History
```
View Statistics:
1. Each profile shows transfer count
2. Total files and data transferred
3. Last successful transfer date
4. Average transfer duration
```

## Troubleshooting Migration

### Issue: "No profiles found"
**Solution:**
1. Check if migration ran (look for `settings.json`)
2. If not, manually create profile:
   - Click "Manage" → "New"
   - Enter same settings as before
   - Test connection
   - Save

### Issue: "Password prompt on every connect"
**Solution:**
1. This means password wasn't saved
2. Open Profile dialog
3. Re-enter password
4. Click "Save"

### Issue: "Old settings.txt still there"
**Solution:**
This is normal! The old file is backed up. You can safely delete it:
```bash
rm ~/.rpi_transfer/settings.txt.backup
```

### Issue: "Encryption key corrupted"
**Solution:**
If `.key` file is corrupted:
1. Delete key file: `rm ~/.rpi_transfer/.key`
2. Delete profiles: `rm ~/.rpi_transfer/profiles.json`
3. Restart app (will create new key and ask for profile creation)

## Performance Comparison

| Feature | v1.x | v2.0 |
|---------|------|------|
| Transfer Speed | Same | Same |
| Preview | No | Yes (background thread) |
| Multiple Devices | No (re-enter each time) | Yes (profiles) |
| History | No | Yes (SQLite) |
| Password Security | Plaintext | Encrypted |
| Settings Format | Text | JSON |
| UI Polish | Basic | Professional |
| File Organization | Auto | Auto + date folders |

## Downgrading (If Needed)

If you need to go back to v1.x:

1. **Revert to old version**
   ```bash
   pip install netcpy==1.0.0
   ```

2. **Restore old settings**
   ```bash
   cp ~/.rpi_transfer/settings.txt.backup ~/.rpi_transfer/settings.txt
   ```

3. **Remove v2.0 files**
   ```bash
   rm ~/.rpi_transfer/*.json ~/.rpi_transfer/history.db ~/.rpi_transfer/.key
   ```

## Getting Help

- Check README.md for feature documentation
- Use "Test Connection" button to verify credentials
- Check log messages for detailed error information
- Review Profile dialog statistics to verify setup

## FAQ

**Q: Do I lose my transfer history?**
A: No! It's migrated to SQLite. Access it via profile statistics.

**Q: Can I use the same password for multiple profiles?**
A: Yes! Each profile stores its own password (encrypted).

**Q: What if my device name changes?**
A: Create a new profile with new name, old profile remains as history.

**Q: Is my password really encrypted?**
A: Yes! Uses Fernet symmetric encryption with keys stored separately.

**Q: Can I share profiles with others?**
A: Not yet, but profiles are in JSON format (easy to export/import in future).

**Q: What about the old application file?**
A: Keep it if you want to revert, but v2.0 is production-ready.

## Version Numbers

- **v1.x**: Single file application (legacy)
- **v2.0**: New modular architecture (current)
- **Semantic Versioning**: Major.Minor.Patch

## Support

For migration issues or questions, refer to the detailed documentation or check the troubleshooting section in README.md.
