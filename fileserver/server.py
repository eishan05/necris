from flask import Flask, render_template, request, send_file, redirect, url_for
import os
from werkzeug.utils import secure_filename
from pathlib import Path

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = '/home/pi/shared'  # Change this to your desired share directory
ALLOWED_EXTENSIONS = {'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'mp4', 'zip'}

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024  # 16MB max file size

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_human_readable_size(size):
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"

@app.route('/')
def index():
    current_path = request.args.get('path', '')
    full_path = os.path.join(UPLOAD_FOLDER, current_path)
    
    # Ensure we don't allow directory traversal
    if not os.path.realpath(full_path).startswith(os.path.realpath(UPLOAD_FOLDER)):
        return redirect(url_for('index'))
    
    files = []
    for item in os.scandir(full_path):
        item_info = {
            'name': item.name,
            'is_dir': item.is_dir(),
            'size': get_human_readable_size(item.stat().st_size) if not item.is_dir() else '',
            'modified': os.path.getmtime(item.path)
        }
        files.append(item_info)
    
    # Sort directories first, then files
    files.sort(key=lambda x: (not x['is_dir'], x['name'].lower()))
    
    return render_template('index.html', 
                         files=files, 
                         current_path=current_path,
                         parent_path=os.path.dirname(current_path))

@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return redirect(request.referrer)
    
    file = request.files['file']
    current_path = request.form.get('current_path', '')
    
    if file.filename == '':
        return redirect(request.referrer)
    
    if file and allowed_file(file.filename):
        filename = secure_filename(file.filename)
        upload_path = os.path.join(UPLOAD_FOLDER, current_path)
        file.save(os.path.join(upload_path, filename))
    
    return redirect(url_for('index', path=current_path))

@app.route('/download/<path:filepath>')
def download_file(filepath):
    full_path = os.path.join(UPLOAD_FOLDER, filepath)
    return send_file(full_path, as_attachment=True)

@app.route('/delete/<path:filepath>')
def delete_file(filepath):
    full_path = os.path.join(UPLOAD_FOLDER, filepath)
    if os.path.exists(full_path):
        os.remove(full_path)
    return redirect(request.referrer)

if __name__ == '__main__':
    # Create upload folder if it doesn't exist
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    # Run the app on all network interfaces
    app.run(host='0.0.0.0', port=80, debug=True)