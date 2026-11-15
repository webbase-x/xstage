"""Measured Google account storage quota and conservative live-sync forecast.

Google Drive About uses the existing drive.file OAuth scope. Storage *usage*
includes all Google account services; usageInDrive is informational only.
The forecast uses only byte sizes from uploads verified during this run. It
never claims to know the final compressed size of unconverted MIDI/NCN files.
"""
from __future__ import annotations

import math

ABOUT_QUOTA_URL = ('https://www.googleapis.com/drive/v3/about?'
                   'fields=storageQuota(limit,usage,usageInDrive,usageInDriveTrash)')


def _bytes_or_none(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = int(value)
    except (ValueError, TypeError, OverflowError):
        return None
    return number if number >= 0 else None


def read_drive_quota(drive):
    """Get the owner's current total-account usage, not only XStageWeb files."""
    data = drive.json(ABOUT_QUOTA_URL)
    quota = data.get('storageQuota') if isinstance(data, dict) else None
    if not isinstance(quota, dict):
        raise ValueError('Google Drive ไม่ส่งข้อมูลความจุบัญชีกลับมา')
    result = {
        'usage': _bytes_or_none(quota.get('usage')),
        'limit': _bytes_or_none(quota.get('limit')),
        'usageInDrive': _bytes_or_none(quota.get('usageInDrive')),
        'usageInDriveTrash': _bytes_or_none(quota.get('usageInDriveTrash')),
    }
    if result['usage'] is None:
        raise ValueError('Google Drive ไม่ส่งข้อมูลพื้นที่ที่ใช้')
    return result


def storage_pct(used, limit):
    if limit is None or limit <= 0 or used is None:
        return None
    return max(0.0, 100.0 * max(0, used) / limit)


def format_bytes(value):
    if value is None:
        return '—'
    value = max(0, int(value))
    for unit in ('B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'):
        if value < 1024 or unit == 'PiB':
            return f'{value:,.0f} {unit}' if unit == 'B' else f'{value:,.2f} {unit}'
        value /= 1024
    return '—'


def projected_storage(quota, stats):
    """Forecast final total-account usage from a rolling window of real uploads.

    Returns None before at least 12 processed songs and 3 songs that actually
    uploaded new files. The window includes reused songs, whose added bytes
    are zero, so previously uploaded music is not blindly counted again.
    Google storage reporting may lag; projections are advisory, never limits.
    """
    if not isinstance(quota, dict) or not isinstance(stats, dict):
        return None
    usage = _bytes_or_none(quota.get('usage'))
    total = _bytes_or_none(stats.get('total'))
    done = _bytes_or_none(stats.get('processed'))
    sample_songs = _bytes_or_none(stats.get('sample_songs'))
    sample_uploads = _bytes_or_none(stats.get('sample_uploads'))
    sample_bytes = _bytes_or_none(stats.get('sample_bytes'))
    if usage is None or total is None or not total or done is None:
        return None
    if done >= total:
        return {'bytes': usage, 'extra_bytes': 0, 'samples': sample_songs or 0,
                'uploads': sample_uploads or 0, 'complete': True}
    if (sample_songs is None or sample_songs < 12 or sample_uploads is None or
            sample_uploads < 3 or sample_bytes is None):
        return None
    remaining = max(0, total - done)
    added = math.ceil(remaining * sample_bytes / sample_songs)
    # Does not add bytes already uploaded and reflected in current Google usage.
    return {'bytes': usage + added, 'extra_bytes': added,
            'samples': sample_songs, 'uploads': sample_uploads,
            'complete': False}
