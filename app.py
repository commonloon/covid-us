from flask import Flask, request, render_template, session, redirect
from io import StringIO
import urllib.request
import urllib.parse
import pandas as pd
import json

app = Flask(__name__)


@app.route('/')
def home():
    df = pd.read_csv('https://api.covidtracking.com/v1/states/daily.csv')
    df.drop(df[df["state"] == 'AS'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    df.drop(df[df["state"] == 'GU'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    df.drop(df[df["state"] == 'MP'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    df.drop(df[df["state"] == 'VI'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    states = sorted(df.state.unique())
    df['day'] = pd.to_datetime(df['date'].apply(str))
    df = df[::-1]
    df['positiveFraction'] = df.positiveIncrease / df.totalTestResultsIncrease
    df['deathIncrease'].clip(-1, inplace=True)  # discard negative values of deathIncrease

    # There are many erroneous reports of zero or fewer new cases, so for now we drop them.
    # I'm uncomfortable with this long term, as states with low absolute numbers could legitimately
    # report zero new cases per day.  But as of June 15, very few states could legitimately have 0 new cases per day.
    df.drop(df[(df["positiveIncrease"] <= 0)].index, inplace=True)

    last_day = max(df.date)

    data = {}
    for state in states:
        s = df.loc[df.state == state, ['day', 'positiveIncrease', 'deathIncrease', 'totalTestResultsIncrease', 'positiveFraction']]
        s.sort_values(by='day', inplace=True)

        s['ncases7day'] = s.positiveIncrease.rolling(7).mean()
        s['ndeaths7day'] = s.deathIncrease.rolling(7).mean()
        s['day'] = s['day'].dt.strftime('%Y-%m-%d')

        data[state] = s.to_dict(orient='records')
    return render_template("home.html", states=states, data=data, last_day=last_day)

@app.route('/get-data')
def get_data():


    return


if __name__ == '__main__':
    app.run()
