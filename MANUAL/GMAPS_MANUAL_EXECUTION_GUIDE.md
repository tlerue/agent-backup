# Google Maps Tracking - Manual Execution Guide

This guide provides comprehensive documentation on how to properly execute Google Maps tracking tasks manually while ensuring all steps are completed, including notification sending.

## Table of Contents
1. [Overview](#overview)
2. [Scripts Overview](#scripts-overview)
3. [Quick Start](#quick-start)
4. [Detailed Usage](#detailed-usage)
5. [Verification](#verification)
6. [Testing](#testing)
7. [Troubleshooting](#troubleshooting)
8. [Best Practices](#best-practices)

## Overview

When executing Google Maps tracking manually, it's important to follow the complete workflow to ensure:
- Data is properly scraped and processed
- Reports are generated correctly
- Notifications are sent automatically
- All files are committed to GitHub

Previously, manually running individual components could result in missing notification steps. This guide addresses that issue.

## Scripts Overview

### 1. `manual_gmaps_run.sh`
**Purpose**: Complete wrapper for manual execution that ensures all steps are performed including notification sending.

**Location**: `/home/user/gmaps_quimper/manual_gmaps_run.sh`

**Usage**:
```bash
cd /home/user/gmaps_quimper
./manual_gmaps_run.sh
```

**What it does**:
1. Runs `scraper_v2.py` to scrape Google Maps data
2. Runs `build_csv_recurrent.py` to process data and generate reports
3. Automatically sends notification via ntfy-send-url.sh

### 2. `verify_manual_run.sh`
**Purpose**: Verification script to check if manual execution completed successfully.

**Location**: `/home/user/gmaps_quimper/verify_manual_run.sh`

**Usage**:
```bash
cd /home/user/gmaps_quimper
./verify_manual_run.sh
```

**What it checks**:
- Snapshot files (.csv)
- Report files (.md)
- Results file (results_v2.json)
- Historical data (historique_classements.csv)

### 3. `test_notification.sh`
**Purpose**: Test script to verify the notification system is working.

**Location**: `/home/user/gmaps_quimper/test_notification.sh`

**Usage**:
```bash
cd /home/user/gmaps_quimper
./test_notification.sh
```

### 4. Documentation
**Purpose**: This comprehensive guide.

**Location**: `/home/user/gmaps_quimper/GMAPS_MANUAL_EXECUTION_GUIDE.md`

## Quick Start

The simplest way to run Google Maps tracking manually is to use the wrapper script:

```bash
cd /home/user/gmaps_quimper
./manual_gmaps_run.sh
```

This single command will:
1. Run the Google Maps scraper (`scraper_v2.py`)
2. Process the data and generate reports (`build_csv_recurrent.py`)
3. Automatically send notification via ntfy.sh

## Detailed Usage

### Using the Wrapper Script (Recommended)

```bash
# Navigate to the Google Maps tracking directory
cd /home/user/gmaps_quimper

# Run the complete manual execution process
./manual_gmaps_run.sh
```

**Expected Output**:
```
=== Google Maps Manual Execution Wrapper ===
Date: Sun Oct 11 18:47:08 UTC 2026

1. Running Google Maps scraping...
✓ Scraping completed successfully

2. Processing data and generating report...
✓ Data processing completed successfully

3. Checking for generated report...
✓ Found report: history/rapports/2026-10-11_pm_rapport.md
4. Sending notification...
✓ Notification sent successfully

=== Manual execution completed ===
```

### Using Convenience Aliases

Convenience aliases have been added to make usage easier:

```bash
# Instead of typing the full path, you can use:
gmaps-run    # Run complete Google Maps tracking
gmaps-verify # Verify that files were generated correctly
gmaps-test   # Test that notification system works
gmaps-help   # Show help information
```

Example:
```bash
gmaps-run
```

## Verification

After running the manual execution, verify everything worked correctly:

```bash
cd /home/user/gmaps_quimper
./verify_manual_run.sh
```

**Sample Output**:
```
=== Google Maps Execution Verification ===
Date: Sun Oct 11 18:45:31 UTC 2026

1. Checking for snapshot file...
✓ PM snapshot found: -rw-r--r-- 1 user user 14K Oct 11 18:28 history/snapshots/2026-10-11_pm.csv

2. Checking for report file...
✓ PM report found: -rw-r--r-- 1 user user 14K Oct 11 18:28 history/rapports/2026-10-11_pm_rapport.md

3. Checking results file...
✓ Results file exists: -rw-r--r-- 1 user user 100K Oct 11 18:27 results_v2.json
  Last modified: 2026-10-11 18:27:39.893853562 +0000

4. Checking historical data...
✓ Historical data exists: -rw-r--r-- 1 user user 212K Oct 11 18:28 historique_classements.csv
  Lines: 2501

5. Report file details:
  Size: 14K
  Last modified: 2026-10-11 18:28:12.179877649 +0000

=== Verification completed ===
```

## Testing

To test that the notification system is working without doing a full run:

```bash
cd /home/user/gmaps_quimper
./test_notification.sh
```

**Sample Output**:
```
=== Testing Notification System ===
Created test file: /tmp/test_notification_1791744338.md
Sending test notification...
[...GitHub push output...]
✅ Notification envoyée avec succès
✓ Test notification sent successfully
✓ Test completed successfully
```

## Troubleshooting

### Issue: Report generated but no notification sent
**Cause**: Running individual components instead of using the wrapper script
**Solution**: Manually send notification using the ntfy-send-url.sh script

```bash
# Find the report file
REPORT_FILE=$(ls history/rapports/*_$(date +%Y-%m-%d)_*.md | tail -1)

# Send notification
/home/user/.agents/skills/ntfy-send-url/ntfy-send-url.sh \
    "$REPORT_FILE" \
    "menez-roch-veur-en-bzh-suivi-google-maps-que-c-est" \
    "Nouveau rapport Google Maps Quimper"
```

### Issue: Files not appearing in expected locations
**Cause**: Date/time mismatch or execution errors
**Solution**: Check the verification script output to see where files were actually created

```bash
./verify_manual_run.sh
```

### Issue: Permission denied errors
**Cause**: Scripts don't have execute permissions
**Solution**: Ensure all scripts have execute permissions

```bash
chmod +x *.sh
```

## Best Practices

1. **Always use the wrapper script** for complete manual executions
   - Ensures all steps including notification sending are performed
   - Reduces chance of human error

2. **Verify results** after manual execution using the verification script
   - Confirms all expected files were generated
   - Helps identify issues early

3. **Test notifications** periodically to ensure the system is working
   - Validates GitHub connectivity
   - Confirms ntfy.sh integration

4. **Document any deviations** from standard procedures
   - Keep notes of any manual interventions
   - Record any issues encountered and their solutions

5. **Check process logs** if something goes wrong
   ```bash
   list_processes  # Then check specific process outputs
   ```

6. **Use convenience aliases** for faster execution
   ```bash
   gmaps-run    # Instead of ./manual_gmaps_run.sh
   gmaps-verify # Instead of ./verify_manual_run.sh
   gmaps-test   # Instead of ./test_notification.sh
   ```

## Common Commands Reference

| Command | Purpose | Usage |
|---------|---------|-------|
| `./manual_gmaps_run.sh` | Complete manual execution | `cd /home/user/gmaps_quimper && ./manual_gmaps_run.sh` |
| `./verify_manual_run.sh` | Verify execution results | `cd /home/user/gmaps_quimper && ./verify_manual_run.sh` |
| `./test_notification.sh` | Test notification system | `cd /home/user/gmaps_quimper && ./test_notification.sh` |
| `gmaps-run` | Alias for manual execution | `gmaps-run` |
| `gmaps-verify` | Alias for verification | `gmaps-verify` |
| `gmaps-test` | Alias for testing | `gmaps-test` |
| `gmaps-help` | Show help information | `gmaps-help` |

## File Locations

- **Main directory**: `/home/user/gmaps_quimper`
- **Reports**: `/home/user/gmaps_quimper/history/rapports/`
- **Snapshots**: `/home/user/gmaps_quimper/history/snapshots/`
- **Historical data**: `/home/user/gmaps_quimper/historique_classements.csv`
- **Scraper results**: `/home/user/gmaps_quimper/results_v2.json`

## Notification Details

Notifications are sent to the ntfy.sh topic: `menez-roch-veur-en-bzh-suivi-google-maps-que-c-est`

Each notification includes:
- A title indicating the type of report
- A message with basic information
- A clickable button that opens the full report in a GitHub Pages viewer

The notification system uses proper URL encoding (with `&` characters, not `&amp;` entities) to ensure buttons display correctly in the ntfy.sh interface.

---

*Last updated: October 11, 2026*