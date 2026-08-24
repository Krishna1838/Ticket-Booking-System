import os
import zipfile

def zip_project(zip_filename="submission.zip"):
    ignore_dirs = {".venv", "__pycache__", "mail_spool", ".git", ".idea", ".pytest_cache"}
    ignore_files = {zip_filename, "booking.db", ".env"}
    
    current_dir = os.path.dirname(os.path.abspath(__file__))
    zip_path = os.path.join(current_dir, zip_filename)
    
    print(f"Creating ZIP archive: {zip_filename}...")
    
    count = 0
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(current_dir):
            # Modify dirs in-place to skip ignored directories
            dirs[:] = [d for d in dirs if d not in ignore_dirs]
            
            for file in files:
                if file in ignore_files or file.endswith(".pyc") or ".db" in file:
                    continue
                    
                file_path = os.path.join(root, file)
                relative_path = os.path.relpath(file_path, current_dir)
                zipf.write(file_path, relative_path)
                print(f"  Added: {relative_path}")
                count += 1
                
    print(f"\nSuccessfully archived {count} files in {zip_filename}!")

if __name__ == "__main__":
    zip_project()
