import json

from flask import Flask, render_template

from src.common import SCHEDULE_FILEPATH

app = Flask(__name__)


@app.route('/')
def index():
    with open(SCHEDULE_FILEPATH, 'r') as file:
        schedule = json.load(file)

    return render_template('index.html', schedule=schedule)
