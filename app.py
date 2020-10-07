from flask import Flask, request, render_template, session, redirect
from io import StringIO
import urllib.request
import urllib.parse
import pandas as pd
import json

app = Flask(__name__)

# The app gets deployed to AWS Lambda as http://<server>/dev, so we need to
# provide a route with the /dev prefix to use in the local test environment,
# e.g. to serve the anchor <a href="/dev/us">
@app.route('/us')
@app.route('/dev/us')
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
    df['totalTestResultsIncrease'].clip(-1, inplace=True)  # discard negative values of totalTestResultsIncrease
    df['positiveFraction'].clip(0, 1.0, inplace=True)  # limit positiveFraction to range [0, 1.0]

    # There are many erroneous reports of zero or fewer new cases, so for now we drop them.
    # I'm uncomfortable with this long term, as states with low absolute numbers could legitimately
    # report zero new cases per day.  But as of June 15, very few states could legitimately have 0 new cases per day.
    df.drop(df[(df["positiveIncrease"] < 0)].index, inplace=True)

    last_day = max(df.date)

    data = {}
    for state in states:
        s = df.loc[df.state == state, ['day', 'positiveIncrease', 'deathIncrease', 'totalTestResultsIncrease', 'positiveFraction']]
        s.sort_values(by='day', inplace=True)

        s['ncases7day'] = s.positiveIncrease.rolling(7).mean()
        s['ndeaths7day'] = s.deathIncrease.rolling(7).mean()
        s['nresults7day'] = s.totalTestResultsIncrease.rolling(7).mean()
        s['pf7day'] = s.positiveFraction.rolling(7).mean()
        s['day'] = s['day'].dt.strftime('%Y-%m-%d')

        data[state] = s.to_dict(orient='records')
    return render_template("us.html", states=states, data=data, last_day=last_day)

# The app gets deployed to AWS Lambda as http://<server>/dev, so we need to
# provide a route with the /dev prefix to use in the local test environment,
# e.g. to serve the anchor <a href="/dev/us">
@app.route('/')
@app.route('/canada')
@app.route('/dev/canada')
def canada():
    cases = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/cases_timeseries_prov.csv')
    provinces = sorted(cases.province.unique())
    prov_map = {
        'Alberta': 'AB',
        'BC': 'BC',
        'Manitoba': 'MB',
        'NL': 'NL',
        'NWT': 'NWT',
        'New Brunswick': 'NB',
        'Nova Scotia': 'NS',
        'Nunavut': 'NU',
        'Ontario': 'ON',
        'PEI': 'PEI',
        'Quebec': 'QC',
        'Repatriated': 'Repatriated',
        'Saskatchewan': 'SK',
        'Yukon': 'YT'
    }

    deaths = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/mortality_timeseries_prov.csv')
    tests = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/testing_timeseries_prov.csv')
    cases['day'] = pd.to_datetime(cases['date_report'].apply(str),dayfirst=True)
    deaths['day'] = pd.to_datetime(deaths['date_death_report'].apply(str),dayfirst=True)
    tests['day'] = pd.to_datetime(tests['date_testing'].apply(str),dayfirst=True)

    # most recent day on which the data was updated
    last_day = max(cases.day).strftime("%Y-%m-%d")

    data = {}
    for prov in provinces:
        c = cases.loc[cases.province == prov, ['day', 'cases']]
        d = deaths.loc[deaths.province == prov, ['day', 'deaths']]
        t = tests.loc[deaths.province == prov, ['day', 'testing']]
        c.sort_values(by='day', inplace=True)
        d.sort_values(by='day', inplace=True)
        t.sort_values(by='day', inplace=True)
        s = pd.merge(c, d, how='left', left_on=['day'], right_on=['day'])
        s = pd.merge(s, t, how='left', left_on=['day'], right_on=['day'])

        s['ncases7day'] = s.cases.rolling(7).mean()
        s['ndeaths7day'] = s.deaths.rolling(7).mean()
        s['nresults7day'] = s.testing.rolling(7).mean()
        s['positiveFraction'] = s.cases / s.testing
        s['pf7day'] = s.positiveFraction.rolling(7).mean()
        s['testing'].clip(-1, inplace=True)  # discard negative numbers of new test results
        s['positiveFraction'].clip(0, 1.0, inplace=True)  # limit positiveFraction to range [0, 1.0]

        s['day'] = s['day'].dt.strftime('%Y-%m-%d')

        data[prov_map[prov]] = s.to_dict(orient='records')
        pass
    return render_template("canada.html", provinces=sorted(prov_map.values()), data=data, last_day=last_day)


if __name__ == '__main__':
    app.run()
