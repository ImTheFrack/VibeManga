import os
import shutil
import tempfile
import zipfile
import logging
import click
import subprocess
import shutil
from pathlib import Path
from typing import List, Optional
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn
from rich.panel import Panel
from rich.prompt import Confirm

from .base import console, get_library_root, run_scan_with_progress
from ..constants import PULL_TEMPDIR, VALID_MANGA_EXTENSIONS
from ..models import Series, Volume
from ..analysis import semantic_normalize

logger = logging.getLogger(__name__)

# Optional imports for JXL support
try:
    import numpy as np
    from PIL import Image
    import imagecodecs
    JXL_SUPPORT = True
except ImportError:
    JXL_SUPPORT = False

# Optional import for 7z support
try:
    import py7zr
    SEVENZIP_SUPPORT = True
except ImportError:
    SEVENZIP_SUPPORT = False

def has_7z_cli() -> bool:
    """Checks if the 7z executable is available in PATH or common locations."""
    if shutil.which("7z"):
        return True
    # Check common Windows paths
    common = [
        r"C:\Program Files\7-Zip\7z.exe",
        r"C:\Program Files (x86)\7-Zip\7z.exe"
    ]
    for p in common:
        if os.path.exists(p):
            os.environ["PATH"] += os.pathsep + os.path.dirname(p)
            return True
    return False

def list_7z_cli(path: Path) -> List[str]:
    """Lists files in archive using 7z CLI."""
    try:
        # -slt provides detailed info, but simple listing is enough for names
        cmd = ["7z", "l", "-ba", str(path)]
        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if result.returncode != 0:
            return []
        
        filenames = []
        for line in result.stdout.splitlines():
            parts = line.split(maxsplit=5)
            if len(parts) >= 6:
                filenames.append(parts[5])
        return filenames
    except Exception as e:
        logger.debug(f"7z CLI list failed: {e}")
        return []

def extract_7z_cli(archive_path: Path, output_dir: Path) -> bool:
    """Extracts archive using 7z CLI."""
    try:
        cmd = ["7z", "x", f"-o{output_dir}", "-y", str(archive_path)]
        result = subprocess.run(cmd, capture_output=True)
        return result.returncode == 0
    except Exception:
        return False

def identify_file_type(path: Path) -> str:
    """Reads the first few bytes to guess the file type."""
    try:
        if not path.exists():
            return "File Missing"
            
        file_size = path.stat().st_size
        if file_size == 0:
            return "Empty File (0 bytes)"
            
        with open(path, 'rb') as f:
            header = f.read(12)
        
        # Check for zeroed out header (common in corrupted downloads)
        if all(b == 0 for b in header):
            return "Zeroed-out File (Corrupt)"
            
        if header.startswith(b'\x89PNG\r\n\x1a\n'): return "PNG Image"
        if header.startswith(b'\xff\xd8\xff'): return "JPEG Image"
        if header.startswith(b'GIF87a') or header.startswith(b'GIF89a'): return "GIF Image"
        if header.startswith(b'BM'): return "BMP Image"
        if header.startswith(b'%PDF'): return "PDF Document"
        if header.startswith(b'Rar!\x1a\x07\x00'): return "RAR Archive (v4)"
        if header.startswith(b'Rar!\x1a\x07\x01\x00'): return "RAR Archive (v5)"
        if header.startswith(b'PK\x03\x04'): return "ZIP Archive"
        if header.startswith(b'7z\xbc\xaf\x27\x1c'): return "7-Zip Archive"
        if header.startswith(b'\x00\x00\x00\x0c\x6a\x50\x20\x20\x0d\x0a\x87\x0a'): return "JPEG 2000 Signature"
        if header.startswith(b'\xff\x4f\xff\x51'): return "JPEG 2000 Codestream"
        if header.startswith(b'\xff\x0a'): return "JPEG XL"
        if header.startswith(b'\x00\x00\x00\x0cJXL \x0d\x0a\x87\x0a'): return "JPEG XL (Container)"
        if header[4:12] == b'ftypavif': return "AVIF Image"
        if header[4:12] == b'ftypheic': return "HEIC Image"
        if header[4:12] == b'ftypisom': return "MP4/ISO Media"
        if header.startswith(b'RIFF') and header[8:12] == b'WEBP': return "WebP Image"
        
        return f"Unknown (Header: {header.hex()[:16]})"
    except Exception as e:
        return f"Unreadable ({e})"

def safe_extract(archive_path: Path, output_dir: Path) -> bool:
    """
    Robustly extracts an archive to output_dir, handling ZIP, RAR, 7z and CLI fallbacks.
    Returns True on success.
    """
    # 1. Try generic ZIP
    try:
        if zipfile.is_zipfile(archive_path):
            try:
                with zipfile.ZipFile(archive_path) as zf:
                    zf.extractall(path=output_dir)
                return True
            except (zipfile.BadZipFile, NotImplementedError):
                # Fallthrough to 7z CLI if basic zip failed
                pass
    except:
        pass

    # 2. Try RAR (via rarfile)
    try:
        is_rar = False
        import rarfile
        if rarfile.is_rarfile(archive_path):
            is_rar = True
            with rarfile.RarFile(archive_path) as rf:
                rf.extractall(path=output_dir)
            return True
    except (ImportError, rarfile.RarCannotExec, rarfile.Error):
        # Fallthrough to 7z CLI if rar failed or unrar missing
        pass
    except:
        # catch all for is_rarfile might fail on some files
        pass

    # 3. Try 7z (via py7zr)
    try:
        if SEVENZIP_SUPPORT and py7zr.is_7zfile(archive_path):
            with py7zr.SevenZipFile(archive_path, mode='r') as z:
                z.extractall(path=output_dir)
            return True
    except:
        pass

    # 4. Fallback: 7z CLI
    if has_7z_cli():
        if extract_7z_cli(archive_path, output_dir):
            return True

    return False

@click.command()
@click.argument("series_name", required=False)
@click.option("--nojxl", is_flag=True, help="Convert JPEG XL (.jxl) files to PNG.")
@click.option("--nocbr", is_flag=True, help="Convert .cbr/.rar files to .cbz (Store, no compression).")
@click.option("--simulate", is_flag=True, help="Simulate changes without modifying files.")
@click.option("-v", "--verbose", count=True, help="Increase verbosity.")
def rebase(series_name: Optional[str], nojxl: bool, nocbr: bool, simulate: bool, verbose: int):
    """
    Refactor archive files in the library.

    Can target a specific series or the entire library.
    
    \b
    Operations:
        --nojxl: Scans archives for .jxl files and converts them to .png.
        --nocbr: Repacks .cbr/.rar files to .cbz (no compression).
    """
    # 1. Validation
    if not (nojxl or nocbr):
        console.print("[yellow]No operation specified. Please use --nojxl, --nocbr, or other flags.[/yellow]")
        return

    if nojxl and not JXL_SUPPORT:
        console.print("[red]Error: JXL support requires additional dependencies.[/red]")
        console.print("Please install: [bold]pip install numpy pillow imagecodecs[/bold]")
        return

    # 2. Setup Logging
    log_level = logging.WARNING
    if verbose == 1:
        log_level = logging.INFO
    elif verbose >= 2:
        log_level = logging.DEBUG
    
    logging.getLogger("vibe_manga").setLevel(log_level)

    # 3. Find Targets
    root_path = get_library_root()
    library = run_scan_with_progress(
        root_path,
        f"[bold green]Scanning library for rebase targets...",
        use_cache=True 
    )

    targets: List[Series] = []
    if series_name:
        norm_query = semantic_normalize(series_name)
        for main_cat in library.categories:
            for sub_cat in main_cat.sub_categories:
                for series in sub_cat.series:
                    norm_series = semantic_normalize(series.name)
                    if norm_query and norm_query in norm_series:
                        targets.append(series)
                    elif series_name.lower() in series.name.lower():
                        targets.append(series)
        
        if not targets:
            console.print(f"[red]No series found matching '{series_name}'[/red]")
            return
        console.print(f"[green]Found {len(targets)} matching series.[/green]")
    else:
        # All series
        for main_cat in library.categories:
            for sub_cat in main_cat.sub_categories:
                targets.extend(sub_cat.series)
        console.print(f"[green]Targeting all {len(targets)} series in library.[/green]")

    # 4. Process
    if nojxl:
        process_nojxl(targets, simulate)
    if nocbr:
        process_nocbr(targets, simulate)

def process_nojxl(targets: List[Series], simulate: bool):
    """
    Iterates through targets and processes JXL conversion.
    """
    total_archives = sum(len(s.volumes) + sum(len(sg.volumes) for sg in s.sub_groups) for s in targets)
    
    console.print(f"Checking {total_archives} archives for JXL files...")
    
    # We need a temp dir
    base_temp = Path(PULL_TEMPDIR) if PULL_TEMPDIR else Path(tempfile.gettempdir())
    work_dir = base_temp / "vibe_manga_rebase_jxl"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task_id = progress.add_task("Scanning archives...", total=total_archives)
            
            for series in targets:
                # Collect all volumes
                all_vols = list(series.volumes)
                for sg in series.sub_groups:
                    all_vols.extend(sg.volumes)
                
                for vol in all_vols:
                    progress.update(task_id, description=f"Checking {vol.name}")
                    
                    if not vol.path.exists():
                        progress.advance(task_id)
                        continue

                    if process_archive_nojxl(vol, work_dir, simulate):
                        # If we modified the file (returned True), log it
                        logger.info(f"Rebased: {vol.name}")
                    
                    progress.advance(task_id)

    finally:
        # Cleanup work dir
        if work_dir.exists():
            try:
                shutil.rmtree(work_dir)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir {work_dir}: {e}")

def process_archive_nojxl(volume: Volume, work_dir: Path, simulate: bool) -> bool:
    """
    Checks an archive for JXL files. If found, converts and repacks.
    Returns True if changes were made.
    """
    try:
        has_jxl = False
        
        # 1. Quick Peek (without full extraction if possible)
        # Try generic zip peek
        try:
            if zipfile.is_zipfile(volume.path):
                with zipfile.ZipFile(volume.path) as zf:
                    for n in zf.namelist():
                        if n.lower().endswith('.jxl'):
                            has_jxl = True
                            break
        except:
            pass
        
        if not has_jxl:
            # Try RAR peek
            try:
                import rarfile
                if rarfile.is_rarfile(volume.path):
                    with rarfile.RarFile(volume.path) as rf:
                        for n in rf.namelist():
                            if n.lower().endswith('.jxl'):
                                has_jxl = True
                                break
            except:
                pass
            
        if not has_jxl and SEVENZIP_SUPPORT:
            # Try 7z peek
            try:
                if py7zr.is_7zfile(volume.path):
                    with py7zr.SevenZipFile(volume.path, mode='r') as z:
                        for n in z.getnames():
                            if n.lower().endswith('.jxl'):
                                has_jxl = True
                                break
            except:
                pass
            
        if not has_jxl and has_7z_cli():
            # Try 7z CLI list
            files = list_7z_cli(volume.path)
            for n in files:
                if n.lower().endswith('.jxl'):
                    has_jxl = True
                    break

        if not has_jxl:
            return False

        # Found JXL!
        console.print(f"[yellow]Found JXL in:[/yellow] {volume.name}")
        
        if simulate:
            console.print(f"  [dim]SIMULATE: 1. Create temp directory: {work_dir / ('processing_' + volume.path.stem)}[/dim]")
            console.print(f"  [dim]SIMULATE: 2. Extract contents using safe_extract logic[/dim]")
            console.print(f"  [dim]SIMULATE: 3. Walk extracted files and convert .jxl -> .png (via imagecodecs/PIL)[/dim]")
            console.print(f"  [dim]SIMULATE: 4. Create new .cbz archive (Deflated)[/dim]")
            console.print(f"  [dim]SIMULATE: 5. Replace original file with new .cbz[/dim]")
            return True

        # 2. Extract
        vol_temp = work_dir / f"processing_{volume.path.stem}"
        if vol_temp.exists():
            shutil.rmtree(vol_temp)
        vol_temp.mkdir()

        extracted_root = vol_temp / "extracted"
        extracted_root.mkdir()

        if not safe_extract(volume.path, extracted_root):
            file_type = identify_file_type(volume.path)
            console.print(f"[red]Error extracting {volume.name}[/red] [dim]Detected: {file_type}[/dim]")
            return False

        # 3. Convert
        converted_count = 0
        for root, _, files in os.walk(extracted_root):
            for file in files:
                if file.lower().endswith('.jxl'):
                    file_path = Path(root) / file
                    try:
                        # Decode JXL
                        image_data = imagecodecs.imread(file_path)
                        
                        # Save as PNG
                        png_path = file_path.with_suffix('.png')
                        Image.fromarray(image_data).save(png_path, format="PNG")
                        
                        # Remove JXL
                        file_path.unlink()
                        converted_count += 1
                    except Exception as e:
                        logger.error(f"Failed to convert {file}: {e}")
                        console.print(f"[red]Failed to convert {file}: {e}[/red]")
                        return False # Abort to avoid data loss

        console.print(f"  Converted {converted_count} images to PNG.")

        # 4. Repack
        new_archive_path = vol_temp / f"{volume.path.stem}.cbz"
        
        with zipfile.ZipFile(new_archive_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for root, _, files in os.walk(extracted_root):
                for file in files:
                    full_path = Path(root) / file
                    arcname = full_path.relative_to(extracted_root)
                    zf.write(full_path, arcname)

        # 5. Replace
        target_path = volume.path.with_suffix('.cbz')
        shutil.move(str(new_archive_path), str(target_path))
        
        if volume.path != target_path:
            volume.path.unlink()
            
        console.print(f"  [green]Repacked to {target_path.name}[/green]")
        return True

    except Exception as e:
        logger.error(f"Error processing {volume.name}: {e}", exc_info=True)
        console.print(f"[red]Error processing {volume.name}: {e}[/red]")
        return False

def process_nocbr(targets: List[Series], simulate: bool):
    """
    Iterates through targets and processes CBR to CBZ conversion.
    """
    total_archives = sum(len(s.volumes) + sum(len(sg.volumes) for sg in s.sub_groups) for s in targets)
    
    console.print(f"Checking {total_archives} archives for .cbr format...")
    
    # We need a temp dir
    base_temp = Path(PULL_TEMPDIR) if PULL_TEMPDIR else Path(tempfile.gettempdir())
    work_dir = base_temp / "vibe_manga_rebase_cbr"
    work_dir.mkdir(parents=True, exist_ok=True)
    
    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
            console=console
        ) as progress:
            task_id = progress.add_task("Scanning archives...", total=total_archives)
            
            for series in targets:
                all_vols = list(series.volumes)
                for sg in series.sub_groups:
                    all_vols.extend(sg.volumes)
                
                for vol in all_vols:
                    progress.update(task_id, description=f"Checking {vol.name}")
                    
                    if not vol.path.exists():
                        progress.advance(task_id)
                        continue

                    # Check extension
                    ext = vol.path.suffix.lower()
                    if ext in ('.cbr', '.rar', '.7z'):
                        if process_archive_nocbr(vol, work_dir, simulate):
                            logger.info(f"Converted: {vol.name}")
                    
                    progress.advance(task_id)

    finally:
        if work_dir.exists():
            try:
                shutil.rmtree(work_dir)
            except Exception as e:
                logger.warning(f"Failed to cleanup temp dir {work_dir}: {e}")

def process_archive_nocbr(volume: Volume, work_dir: Path, simulate: bool) -> bool:
    """
    Converts .cbr/.rar/.7z to .cbz (Stored, No Compression).
    """
    try:
        # 1. Check if it's already a ZIP (renamed .cbr)
        if zipfile.is_zipfile(volume.path):
            # It's a zip! just rename it
            console.print(f"[cyan]Renaming Fake CBR:[/cyan] {volume.name}")
            if simulate:
                console.print(f"  [dim]SIMULATE: Rename {volume.path.name} -> {volume.path.with_suffix('.cbz').name}[/dim]")
                return True
            
            target_path = volume.path.with_suffix('.cbz')
            shutil.move(str(volume.path), str(target_path))
            console.print(f"  [green]Renamed to {target_path.name}[/green]")
            return True

        # It's a real RAR or 7z or corrupt.
        file_type = identify_file_type(volume.path)
        if "RAR" not in file_type and "7-Zip" not in file_type:
            console.print(f"[red]Skipping Unknown:[/red] {volume.name} [dim]Detected: {file_type}[/dim]")
            return False

        console.print(f"[cyan]Converting CBR->CBZ:[/cyan] {volume.name}")
        
        if simulate:
            console.print(f"  [dim]SIMULATE: 1. Create temp directory: {work_dir / ('processing_' + volume.path.stem)}[/dim]")
            console.print(f"  [dim]SIMULATE: 2. Extract contents using safe_extract logic ({file_type})[/dim]")
            console.print(f"  [dim]SIMULATE: 3. Create new .cbz archive (STORED/No Compression)[/dim]")
            console.print(f"  [dim]SIMULATE: 4. Move new .cbz to: {volume.path.with_suffix('.cbz')}[/dim]")
            console.print(f"  [dim]SIMULATE: 5. Delete original file: {volume.path.name}[/dim]")
            return True

        # 2. Extract
        vol_temp = work_dir / f"processing_{volume.path.stem}"
        if vol_temp.exists():
            shutil.rmtree(vol_temp)
        vol_temp.mkdir()

        extracted_root = vol_temp / "extracted"
        extracted_root.mkdir()

        if not safe_extract(volume.path, extracted_root):
            console.print(f"[red]Error extracting {volume.name}[/red] [dim]Detected: {file_type}[/dim]")
            return False

        # 3. Repack (STORED)
        new_archive_path = vol_temp / f"{volume.path.stem}.cbz"
        
        with zipfile.ZipFile(new_archive_path, 'w', zipfile.ZIP_STORED) as zf:
            for root, _, files in os.walk(extracted_root):
                for file in files:
                    full_path = Path(root) / file
                    arcname = full_path.relative_to(extracted_root)
                    zf.write(full_path, arcname)

        # 4. Replace
        target_path = volume.path.with_suffix('.cbz')
        shutil.move(str(new_archive_path), str(target_path))
        
        if volume.path != target_path:
            volume.path.unlink()
            
        console.print(f"  [green]Converted to {target_path.name}[/green]")
        return True

    except Exception as e:
        logger.error(f"Error processing {volume.name}: {e}", exc_info=True)
        console.print(f"[red]Error processing {volume.name}: {e}[/red]")
        return False