import os
import tempfile
import zipfile

from bs4 import BeautifulSoup
from flask import Flask, request, send_file, session, render_template
from openai import OpenAI
from werkzeug.utils import secure_filename

# Initialize Flask app
app = Flask(__name__)
app.config["SECRET_KEY"] = "your_secret_key"
app.config["SESSION_TYPE"] = "filesystem"

# Initialize OpenAI
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

PREDEFINED_LOCALES = ["en", "de", "it", "ru"]


@app.route('/', methods=['GET'])
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_files():
    files = request.files.getlist('files')
    if not files:
        return "No files uploaded", 400

    file_paths = []
    file_names = []
    temp_dir = tempfile.mkdtemp()

    for file in files:
        if file and file.filename:
            original_filename = secure_filename(file.filename)
            file_path = os.path.join(temp_dir, original_filename)
            file.save(file_path)
            file_paths.append(file_path)
            file_names.append(original_filename)

    session['file_paths'] = file_paths
    session['file_names'] = file_names

    files_with_indices = [(element_index, name) for element_index, name in enumerate(file_names)]

    return render_template('locales.html', files_with_indices=files_with_indices,
                           locales=PREDEFINED_LOCALES)


@app.route('/generate_audio', methods=['POST'])
def generate_audio():
    file_paths = session.get('file_paths')
    file_names = session.get('file_names')

    if not file_paths or not file_names:
        return "No files available for processing", 400

    temp_dir = tempfile.mkdtemp()
    archive_path = os.path.join(temp_dir, "processed_audio_files.zip")

    with zipfile.ZipFile(archive_path, 'w') as zipf:
        for file_path, file_name in zip(file_paths, file_names):
            selected_locales = request.form.getlist(f"{file_name}_locales")
            with open(file_path, 'rb') as file:
                html_content = file.read()

            texts_to_synthesize, _ = parse_html_for_text(html_content)
            add_texts_to_archive(texts_to_synthesize, selected_locales, file_name, zipf, temp_dir)

    return send_file(archive_path, as_attachment=True, download_name="processed_audio_files.zip")


def parse_html_for_text(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    texts = []

    language_row = soup.find_all('tr')[1]
    lang_cells = language_row.find_all('td')

    lang_columns = []
    for cell in lang_cells[2:]:
        text = cell.text.strip()
        start = text.find('(')
        end = text.find(')')
        if start != -1 and end != -1:
            lang_code = text[start + 1:end]
            lang_columns.append(lang_code)
        else:
            lang_columns.append(text)

    rows = soup.find_all('tr')[2:]
    for row in rows:
        cells = row.find_all('td')
        key = cells[0].text.strip() if cells else None

        if key:
            lang_texts = {'key': key}

            for i, lang in enumerate(lang_columns):
                if i + 2 < len(cells):
                    lang_texts[lang] = cells[i + 2].text.strip()
                else:
                    lang_texts[lang] = ""

            texts.append(lang_texts)

    print("Extracted Language Columns:", lang_columns)

    return texts, lang_columns


def add_texts_to_archive(texts, lang_columns, original_filename, zipf, temp_dir):
    input_model = request.form['model']
    input_voice = request.form['voice']

    base_name = os.path.splitext(original_filename)[0]
    for text in texts:
        for lang in lang_columns:
            print(f"Processing language: {lang}, key: {text['key']}")
            file_name = f"{lang}-{text['key']}.mp3"
            temp_audio_path = os.path.join(temp_dir, file_name)

            if text[lang].strip():
                generate_speech(text[lang], temp_audio_path, input_model, input_voice)

                if os.path.exists(temp_audio_path):
                    archive_file_path = os.path.join("Audio", base_name, lang, file_name)
                    zipf.write(temp_audio_path, arcname=archive_file_path)
                    os.remove(temp_audio_path)
                else:
                    print(f"File not created: {temp_audio_path}")
            else:
                print(f"Skipping empty text for language: {lang}, key: {text['key']}")


def generate_speech(input_text, file_path, input_model, input_voice):
    if not input_text.strip():
        print(f"Skipping empty input text for file: {file_path}")
        return

    response = client.audio.speech.create(
        model=input_model,
        voice=input_voice,
        input=input_text
    )
    with open(file_path, "wb") as f:
        f.write(response.content)


if __name__ == "__main__":
    app.run(debug=True)
