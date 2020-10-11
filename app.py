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
    national_df = pd.read_csv('https://api.covidtracking.com/v1/us/daily.csv')
    national_df['day'] = pd.to_datetime(national_df['date'].apply(str))
    national_df['positiveFraction'] = national_df.positiveIncrease / national_df.totalTestResultsIncrease
    national_df = national_df[::-1]
    states_df = pd.read_csv('https://api.covidtracking.com/v1/states/daily.csv')
    states_df.drop(states_df[states_df["state"] == 'AS'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    states_df.drop(states_df[states_df["state"] == 'GU'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    states_df.drop(states_df[states_df["state"] == 'MP'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    states_df.drop(states_df[states_df["state"] == 'VI'].index, inplace=True)  # skip small territories  'GU', 'MP', 'VI']
    states = sorted(states_df.state.unique())
    states_df['day'] = pd.to_datetime(states_df['date'].apply(str))
    states_df = states_df[::-1]
    states_df['positiveFraction'] = states_df.positiveIncrease / states_df.totalTestResultsIncrease
    states_df['deathIncrease'].clip(-1, inplace=True)  # discard negative values of deathIncrease
    states_df['totalTestResultsIncrease'].clip(-1, inplace=True)  # discard negative values of totalTestResultsIncrease
    states_df['positiveFraction'].clip(0, 1.0, inplace=True)  # limit positiveFraction to range [0, 1.0]

    # There are many erroneous reports of zero or fewer new cases, so for now we drop them.
    # I'm uncomfortable with this long term, as states with low absolute numbers could legitimately
    # report zero new cases per day.  But as of June 15, very few states could legitimately have 0 new cases per day.
    states_df.drop(states_df[(states_df["positiveIncrease"] < 0)].index, inplace=True)

    last_day = max(states_df.date)

    # gather the relevant data for the states
    data = {}
    for state in states:
        s = states_df.loc[states_df.state == state, ['day', 'positiveIncrease', 'deathIncrease', 'totalTestResultsIncrease', 'positiveFraction']]
        s.sort_values(by='day', inplace=True)

        s['ncases7day'] = s.positiveIncrease.rolling(7).mean()
        s['ndeaths7day'] = s.deathIncrease.rolling(7).mean()
        s['nresults7day'] = s.totalTestResultsIncrease.rolling(7).mean()
        s['pf7day'] = s.positiveFraction.rolling(7).mean()
        s['day'] = s['day'].dt.strftime('%Y-%m-%d')

        data[state] = s.to_dict(orient='records')

    # gather the relevant national data
    us_data = national_df.filter(['day', 'positiveIncrease', 'deathIncrease', 'totalTestResultsIncrease', 'positiveFraction'], axis=1)
    us_data['ncases7day'] = us_data.positiveIncrease.rolling(7).mean()
    us_data['ndeaths7day'] = us_data.deathIncrease.rolling(7).mean()
    us_data['nresults7day'] = us_data.totalTestResultsIncrease.rolling(7).mean()
    us_data['pf7day'] = us_data.positiveFraction.rolling(7).mean()
    us_data['day'] = us_data['day'].dt.strftime('%Y-%m-%d')
    data['US'] = us_data.to_dict(orient='records')
    states.append('US')

    return render_template("us.html", states=states, data=data, last_day=last_day)

# The app gets deployed to AWS Lambda as http://<server>/dev, so we need to
# provide a route with the /dev prefix to use in the local test environment,
# e.g. to serve the anchor <a href="/dev/us">
@app.route('/')
@app.route('/canada')
@app.route('/dev/canada')
def canada():
    cases = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/cases_timeseries_prov.csv')
    deaths = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/mortality_timeseries_prov.csv')
    tests = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/testing_timeseries_prov.csv')
    cases['day'] = pd.to_datetime(cases['date_report'].apply(str),dayfirst=True)
    deaths['day'] = pd.to_datetime(deaths['date_death_report'].apply(str),dayfirst=True)
    tests['day'] = pd.to_datetime(tests['date_testing'].apply(str),dayfirst=True)
    national_cases = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_canada/cases_timeseries_canada.csv')
    national_deaths = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/mortality_timeseries_prov.csv')
    national_tests = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/testing_timeseries_prov.csv')
    national_cases['day'] = pd.to_datetime(national_cases['date_report'].apply(str),dayfirst=True)
    national_deaths['day'] = pd.to_datetime(national_deaths['date_death_report'].apply(str),dayfirst=True)
    national_tests['day'] = pd.to_datetime(national_tests['date_testing'].apply(str),dayfirst=True)

    # most recent day on which the data was updated
    last_day = max(cases.day).strftime("%Y-%m-%d")

    # Get list of provinces
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
        'Yukon': 'YT',
        'Canada': 'Canada'
    }


    data = {}
    for prov in provinces:
        c = cases.loc[cases.province == prov, ['day', 'cases']]
        d = deaths.loc[deaths.province == prov, ['day', 'deaths']]
        t = tests.loc[deaths.province == prov, ['day', 'testing']]
        data[prov_map[prov]] = canada_to_dict(c, d, t)
        pass
    # add the national data
    data[prov_map['Canada']] = canada_to_dict(national_cases.filter(['day', 'cases'], axis=1),
                                              national_deaths.filter(['day', 'deaths'], axis=1),
                                              national_tests.filter(['day', 'testing'], axis=1))
    return render_template("canada.html", provinces=sorted(prov_map.values()), data=data, last_day=last_day)

def canada_to_dict(c, d, t):
    """
    Canadian data comes from several different files that need to be bundled up
    into a dict to be passed to the rendering template.
    This function does that bundling for the data from a single region.
    :param c: case data for a province or the entire country
    :param d: death data for a province or the entire country
    :param t: test results per day data for a province or the entire country
    :return:
    """
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

    return s.to_dict(orient='records')


if __name__ == '__main__':
    app.run()
