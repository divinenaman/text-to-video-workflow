FROM python:3.11

RUN apt update -y

RUN apt-get install ffmpeg libsm6 libxext6 imagemagick -y

RUN pip install --upgrade pip

COPY requirements.txt .
RUN pip install -q -r requirements.txt

RUN python -m textblob.download_corpora

COPY nltk_download.py .
RUN python nltk_download.py

COPY *.tar.gz ./
RUN pip install *.tar.gz

COPY . .

EXPOSE 5000

RUN mkdir -p /tmp/logs

# CMD ["gunicorn", "--workers", "4", "--bind", "0.0.0.0:5000", "wsgi:app"]

CMD ["python", "app.py"]
