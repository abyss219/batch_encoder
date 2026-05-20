# Batch Encoder

Batch Encoder is a small FFmpeg-based tool for converting videos to HEVC or AV1 with resume support, size checks, optional VMAF verification, progress bars, and structured run reports.

## Requirements

- Python 3.9+
- FFmpeg and ffprobe available on `PATH`
- FFmpeg must include `libx265`, `libsvtav1`, `libaom-av1`, and `libvmaf`

Install Python dependencies:

```bash
python -m pip install -r requirements.txt
```

If you use the repo virtual environment:

```bash
.venv/bin/python batch_encoding.py --help
```

## Batch Encoding

The batch script accepts a directory, a text file containing video paths, or a single video file.

Encode every supported video under a directory:

```bash
python batch_encoding.py /path/to/videos --codec hevc
```

Encode paths from a text file:

```bash
python batch_encoding.py /path/to/video_list.txt --codec hevc
```

List files use one path per line. Empty lines and lines beginning with `#` are ignored. Relative paths are resolved from the list file's directory.

## Skip Codecs

`--force` has been removed. Use `--skip-codecs` for all codec skip behavior.

```bash
python batch_encoding.py /path/to/videos --codec hevc --skip-codecs efficient
```

`efficient` skips AV1, HEVC, VP9, VVC, and Theora.

```bash
python batch_encoding.py /path/to/videos --codec hevc --skip-codecs hevc
```

This only skips HEVC, so AV1 or VP9 sources can still be re-encoded to HEVC.

```bash
python batch_encoding.py /path/to/videos --codec hevc --skip-codecs none
```

This re-encodes all video codecs.

## Config

Defaults live in `config.yaml`. Command-line arguments override config values.

The `batch` section controls batch defaults:

```yaml
batch:
  codec: "hevc"
  min_size: "100MB"
  min_resolution:
  denoise:
  skip_codecs: "efficient"
```

Boolean options can be explicitly enabled or disabled:

```bash
python batch_encoding.py /path/to/videos --verify --no-delete-origin
python batch_encoding.py /path/to/videos --no-check-size
```

## Results

Each run gets a unique run id that includes the target file/folder/list name, a short target hash, and a nonce. Logs and reports are written under `logs/`:

- `batch_encoder_<run_id>.log`
- `batch_encoder_<run_id>_summary.json`
- `batch_encoder_state_<state_id>.pkl`

The final log and JSON report keep exact result states:

- `SUCCESS`: encoding completed and cleanup checks passed.
- `SKIPPED`: file was not encoded, for example below size threshold or already in a skipped codec.
- `FAILED`: encoding or preparation failed.
- `LOWQUALITY`: encoded file failed the VMAF threshold.
- `LARGESIZE`: encoded file was larger than the original.

## Single File Encoding

`encoding.py` remains available for direct single-file encoding:

```bash
python encoding.py /path/to/video.mkv --codec hevc --output-path /path/to/output
```
