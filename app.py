from flask import Flask, render_template
import pandas as pd
from numpy import nanmax, inf, nan
import boto3
from datetime import datetime
import pyarrow
import fastparquet

import time
# import yappi
# import atexit
#
# # End profiling and save the results into file
# def output_profiler_stats_file():
#     profile_file_name = 'yappi.' + datetime.now().isoformat()
#     func_stats = yappi.get_func_stats()
#     func_stats.save(profile_file_name, type='pstat')
#     yappi.stop()
#     yappi.clear_stats()
#
#
# yappi.start()  # start profiler
# atexit.register(output_profiler_stats_file)  # ensure profile gets saved

app = Flask(__name__)

# The app gets deployed to AWS Lambda as http://<server>/dev, so we need to
# provide a route with the /dev prefix to use in the local test environment,
# e.g. to serve the anchor <a href="/dev/us">
@app.route('/us')
@app.route('/dev/us')
def us():
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

    states_pop = {row[0]: row[1] for _, row in pd.read_csv("static/US_2020_pop_estimates.csv").iterrows()}

    # There are many erroneous reports of zero or fewer new cases, so for now we drop them.
    # I'm uncomfortable with this long term, as states with low absolute numbers could legitimately
    # report zero new cases per day.  But as of June 15, very few states could legitimately have 0 new cases per day.
    states_df.drop(states_df[(states_df["positiveIncrease"] < 0)].index, inplace=True)

    last_day = max(states_df.date)
    last_day = datetime.strptime(str(last_day), '%Y%m%d').strftime('%Y-%m-%d')

    # gather the relevant data for the states
    data = {}
    maxPerCapCases = 0
    maxPerCapDeaths = 0
    for state in states:
        s = states_df.loc[states_df.state == state,
                          ['day', 'positiveIncrease', 'deathIncrease',
                           'totalTestResultsIncrease', 'positiveFraction',
                           'hospitalizedCurrently', 'inIcuCurrently']]
        s.sort_values(by='day', inplace=True)
        start_date = datetime.strptime("2020-03-15", '%Y-%m-%d')
        s.drop(s[s["day"] < start_date].index, inplace=True)      # drop entries prior to start_date

        # replace inf and NaN values of positiveFraction with the previous valid value
        s['positiveFraction'].replace(inf, nan, inplace=True)
        s['positiveFraction'].fillna(method='ffill', inplace=True)

        s['ncases7day'] = s.positiveIncrease.rolling(7).mean()
        s['ndeaths7day'] = s.deathIncrease.rolling(7).mean()
        s['nresults7day'] = s.totalTestResultsIncrease.rolling(7).mean()
        s['pf7day'] = s.positiveFraction.rolling(7).mean()
        s['perCapCases'] = s.positiveIncrease * 100000.0 / states_pop[state]
        s['perCapCases7day'] = s.perCapCases.rolling(7).mean()
        s['perCapDeaths'] = s.deathIncrease * 100000.0 / states_pop[state]
        s['perCapDeaths7day'] = s.perCapDeaths.rolling(7).mean()
        s['hosp7day'] = s.hospitalizedCurrently.rolling(7).mean()
        s['icu7day'] = s.inIcuCurrently.rolling(7).mean()

        # we need max values so we can do all the per capita plots to the same scale
        # We use the rolling averages to set the axes because outliers on the individual points make
        # the scale too big.
        maxPerCapCases = max(maxPerCapCases, nanmax(s.perCapCases7day))
        maxPerCapDeaths = max(maxPerCapDeaths, nanmax(s.perCapDeaths7day))

        s['day'] = s['day'].dt.strftime('%Y-%m-%d')

        data[state] = s.to_dict(orient='records')

    # need to sum states to get national values for inIcuCurrently and hospitalizedIncrease
    tmp = states_df[['day', 'hospitalizedCurrently', 'inIcuCurrently']].groupby('day').sum()
    # gather the relevant national data
    us_data = national_df.filter(['day', 'positiveIncrease', 'deathIncrease', 'totalTestResultsIncrease', 'positiveFraction'], axis=1)
    # merge in the sums for inIcuCurrently and hospitalizedIncrease
    us_data = pd.merge(us_data, tmp, how='left', left_on=['day'], right_on=['day'])
    # replace inf and NaN values of positiveFraction with the previous valid value
    us_data['positiveFraction'].replace(inf, nan, inplace=True)
    us_data['positiveFraction'].fillna(method='ffill', inplace=True)

    # calculate the 7 day rolling averages
    us_data['ncases7day'] = us_data.positiveIncrease.rolling(7).mean()
    us_data['ndeaths7day'] = us_data.deathIncrease.rolling(7).mean()
    us_data['nresults7day'] = us_data.totalTestResultsIncrease.rolling(7).mean()
    us_data['pf7day'] = us_data.positiveFraction.rolling(7).mean()
    us_data['perCapCases'] = us_data.positiveIncrease * 100000.0 / states_pop['USA']
    us_data['perCapCases7day'] = us_data.perCapCases.rolling(7).mean()
    us_data['perCapDeaths'] = us_data.deathIncrease * 100000.0 / states_pop['USA']
    us_data['perCapDeaths7day'] = us_data.perCapDeaths.rolling(7).mean()
    us_data['hosp7day'] = us_data.hospitalizedCurrently.rolling(7).mean()
    us_data['icu7day'] = us_data.inIcuCurrently.rolling(7).mean()
    us_data['day'] = us_data['day'].dt.strftime('%Y-%m-%d')
    data['USA'] = us_data.to_dict(orient='records')
    states.append('USA')

    rendered = render_template("us.html", states=states, data=data, last_day=last_day,
                               maxPerCapCases=maxPerCapCases,
                               maxPerCapDeaths=maxPerCapDeaths)
    write_html_to_s3(rendered, "us.html", "covid.pacificloon.ca")
    return "<html><head><meta http-equiv=\"Refresh\" content=\"0; URL=http://covid.pacificloon.ca/us.html\"></head><body><p>Updated canada.html</p></body></html>"

def plot_ecdc_dataset(df, countries, output_filename, last_day, max_per_capita,
                      title,
                      headline,
                      source_data_url, ):
    """

    :param df: dataframe containing the relevant data
    :param countries: list of countries to plot
    :param output_filename: name of the resulting HTML file in the S3 bucket
    :param last_day: day when the source data was last updated
    :param max_per_capita: used to set a fixed scale for plots of per capita data, so countries compare easily
    :return:
    """
    data = {}
    for country in countries:
        pop = df.loc[df.countriesAndTerritories == country, 'popData2019'].iloc[0]
        s = df.loc[df.countriesAndTerritories == country, ['day', 'cases', 'deaths',
                                                           'Cumulative_number_for_14_days_of_COVID-19_cases_per_100000']]
        s.sort_values(by='day', inplace=True)
        s['Cumulative_number_for_14_days_of_COVID-19_cases_per_100000'] /= 14  # we want /100k pop, not the 14 day accumulation

        s['totalTestResultsIncrease'] = 0
        s['positiveFraction'] = 0
        s['ncases7day'] = s.cases.rolling(7).mean()
        s['ndeaths7day'] = s.deaths.rolling(7).mean()
        s['nresults7day'] = 0
        s['pf7day'] = 0
        s['percapDeaths'] = s.deaths * 100000.0 / pop  # per 100k population
        s['percapDeaths7day'] = s.ndeaths7day * 100000.0 / pop
        data[country] = s.to_dict(orient='records')

    # render the HTML file and save it to S3
    rendered = render_template("world.html",
                               countries=countries,
                               data=data,
                               last_day=last_day,
                               max_per_capita=max_per_capita,
                               title=title,
                               headline=headline,
                               source_data_url=source_data_url)
    write_html_to_s3(rendered, output_filename, "covid.pacificloon.ca")

def plot_ecdc_totals(df, last_day, title, headline, source_data_url):
    world_df = df.groupby(['day'])[['day', 'cases', 'deaths']].sum()
    world_df.reset_index(level=['day'],inplace=True)
    world_df.sort_values(by='day', inplace=True)
    world_df['ncases7day'] = world_df.cases.rolling(7).mean()
    world_df['ndeaths7day'] = world_df.deaths.rolling(7).mean()
    world_df.dropna(inplace=True)

    data = {}
    data['Worldwide'] = world_df.to_dict(orient='records')

    # render the HTML file and save it to S3
    rendered = render_template("global.html",
                               countries=["Worldwide"],
                               data=data,
                               last_day=last_day,
                               title=title,
                               headline=headline,
                               source_data_url=source_data_url)
    write_html_to_s3(rendered, "worldwide.html", "covid.pacificloon.ca")

@app.route('/bing')
@app.route('/dev/bing')
def bing():
    df = pd.read_parquet(
        "https://pandemicdatalake.blob.core.windows.net/public/curated/covid-19/bing_covid-19_data/latest/bing_covid-19_data.parquet")
    pass

@app.route('/europe')
@app.route('/dev/europe')
def europe():
    """
    This function started with me looking for a way to plot European data, but
    evolved as the data file turned out to contain worldwide data.

    :return:
    """
    #df = pd.read_csv('https://opendata.ecdc.europa.eu/covid19/casedistribution/csv/data.csv')
    df = pd.read_csv('static/world_to_dec_14.csv')
    df['day'] = pd.to_datetime(df['dateRep'].apply(str),dayfirst=True)
    df['day'] = df['day'].dt.strftime('%Y-%m-%d')
    last_day = max(df.day)
    max_per_capita = 100 # pick an arbitrary number that should work as of Nov 15, 2020

    # countries = sorted(df.countriesAndTerritories.unique())
    plot_ecdc_totals(df, last_day,
                     title='Worldwide Covid Cases',
                     headline="Sum of all the individual country data.",
                     source_data_url="https://data.europa.eu/euodp/en/data/dataset/covid-19-coronavirus-data")

    # drop negative death counts, e.g. Spain had a very large negative death count in June
    # which makes the plot very hard to read.
    df.drop(df[(df["deaths"] < 0)].index, inplace=True)

    # select the countries to plot for each region.
    # There's no particular reason for choosing these countries, other than I was interested in
    # seeing the corresponding charts.
    europe = sorted(['France', 'Germany', 'Denmark', 'Spain', 'Greece', 'Italy',
                     'United_Kingdom', 'Netherlands', 'Poland', 'Estonia', 'Latvia',
                     'Russia', 'Norway', 'Sweden', 'Switzerland', 'Belgium', 'Hungary', 'Romania',
                     'Croatia', 'Austria', 'Belarus', 'Czechia', 'Ukraine', 'Ireland', 'Finland',
                     'Iceland', 'Bulgaria', 'Malta', 'Serbia', 'Cyprus', 'Albania',
                     'Slovenia', 'Slovakia', 'Moldova', 'Kosovo', "Portugal"])
    asia = sorted(['China', 'India', 'Pakistan', 'Bangladesh', 'Thailand', 'Laos', 'Myanmar', 'Indonesia',
                   'Malaysia', 'Australia', 'New_Zealand', 'Mongolia', 'Afghanistan', 'Iran', 'Turkey',
                   'Israel', 'Jordan', 'Saudi_Arabia', 'South_Korea', 'Philippines', 'Singapore'])
    africa = sorted(['Ethiopia', 'Sudan', 'Congo', 'Nigeria', 'Morocco', 'Ghana', 'South_Africa',
                    'Kenya', 'Egypt', 'Libya', 'Tunisia', 'Algeria', 'Namibia', 'Uganda'])
    americas = sorted(['Canada', 'United_States_of_America', 'Mexico', 'Brazil', 'Chile', 'Argentina',
                       'Guatemala', 'Costa_Rica', 'Haiti', 'Cuba', 'Venezuela', 'Colombia', 'Bolivia',
                       'Peru', 'Uruguay', 'Paraguay', 'Belize', 'Jamaica'])

    plot_ecdc_dataset(df, asia, 'asia.html', last_day, max_per_capita,
                      title='Asian Covid Charts',
                      headline="Covid Data for an arbitrary subset of Asian and Polynesian countries",
                      source_data_url="https://data.europa.eu/euodp/en/data/dataset/covid-19-coronavirus-data")
    plot_ecdc_dataset(df, africa, 'africa.html', last_day, max_per_capita,
                      title='African Covid Charts',
                      headline="Covid Data for an arbitrary subset of African countries",
                      source_data_url="https://data.europa.eu/euodp/en/data/dataset/covid-19-coronavirus-data")
    plot_ecdc_dataset(df, americas, 'americas.html', last_day, max_per_capita,
                      title='Americas Covid Charts',
                      headline="Covid Data for an arbitrary subset of countries in the Americas",
                      source_data_url="https://data.europa.eu/euodp/en/data/dataset/covid-19-coronavirus-data")
    plot_ecdc_dataset(df, europe, 'europe.html', last_day, max_per_capita,
                      title='European Covid Charts',
                      headline="Covid Data for an arbitrary subset of European countries",
                      source_data_url="https://data.europa.eu/euodp/en/data/dataset/covid-19-coronavirus-data")

    # return an HTTP redirect to the static file in S3
    return "<html><head><meta http-equiv=\"Refresh\" content=\"0; URL=http://covid.pacificloon.ca/europe.html\"></head><body><p>Updated europe.html</p></body></html>"


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
    national_deaths = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_canada/mortality_timeseries_canada.csv')
    national_tests = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_canada/testing_timeseries_canada.csv')
    national_cases['day'] = pd.to_datetime(national_cases['date_report'].apply(str),dayfirst=True)
    national_deaths['day'] = pd.to_datetime(national_deaths['date_death_report'].apply(str),dayfirst=True)
    national_tests['day'] = pd.to_datetime(national_tests['date_testing'].apply(str), dayfirst=True)

    # get hospitalization data
    arcgis = pd.read_csv('https://opendata.arcgis.com/datasets/3afa9ce11b8842cb889714611e6f3076_0.csv')
    arcgis['day'] = pd.to_datetime(arcgis['SummaryDate'].apply(str),
                                   dayfirst=False, format="%Y/%m/%d").dt.tz_convert(None)
    arcgis.day -= pd.Timedelta(hours=12)

    # most recent day on which the data was updated
    last_day = max(cases.day).strftime("%Y-%m-%d")
    arcgis_last_day = max(arcgis.day).strftime("%Y-%m-%d")

    # get ICU capacity
    icu_beds = {row[1]: int(row[3].replace(',', '')) for _, row in pd.read_csv("static/canada_icu_beds.csv").iterrows()}

    # Get list of provinces.
    # Skip 'Repatriated' as that data was never complete enough to be useful
    provinces = sorted(cases.province.unique())
    provinces.remove('Repatriated')
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
        'Saskatchewan': 'SK',
        'Yukon': 'YT',
        'Canada': 'Canada'
    }

    data = {}
    for prov in provinces:
        arcgis_abbrev = prov_map[prov]
        c = cases.loc[cases.province == prov, ['day', 'cases']]
        d = deaths.loc[deaths.province == prov, ['day', 'deaths']]
        t = tests.loc[tests.province == prov, ['day', 'testing']]
        a = arcgis.loc[arcgis.Abbreviation == arcgis_abbrev, ['day', 'TotalActive']]
        h = arcgis.loc[arcgis.Abbreviation == arcgis_abbrev, ['day', 'TotalHospitalized']]
        i = arcgis.loc[arcgis.Abbreviation == arcgis_abbrev, ['day', 'TotalICU']]
        data[prov_map[prov]] = canada_to_dict(prov, c, d, t, a, h, i)
        pass

    # add the national data
    data[prov_map['Canada']] = canada_to_dict('Canada',
                                              national_cases.filter(['day', 'cases'], axis=1),
                                              national_deaths.filter(['day', 'deaths'], axis=1),
                                              national_tests.filter(['day', 'testing'], axis=1),
                                              arcgis.loc[arcgis.Abbreviation == 'CA', ['day', 'TotalActive']],
                                              arcgis.loc[arcgis.Abbreviation == 'CA', ['day', 'TotalHospitalized']],
                                              arcgis.loc[arcgis.Abbreviation == 'CA', ['day', 'TotalICU']]
                                              )
    # render the HTML file and save it to S3
    rendered = render_template("canada.html", provinces=sorted(prov_map.values()), data=data,
                               last_day=last_day, arcgis_last_day=arcgis_last_day, icu_beds=icu_beds)
    write_html_to_s3(rendered, "canada.html", "covid.pacificloon.ca")

    # return an HTTP redirect to the static file in S3
    return "<html><head><meta http-equiv=\"Refresh\" content=\"0; URL=http://covid.pacificloon.ca/canada.html\"></head><body><p>Updated canada.html</p></body></html>"


def canada_to_dict(province, c, d, t, a, h, i):
    """
    Canadian data comes from several different files that need to be bundled up
    into a dict to be passed to the rendering template.
    This function does that bundling for the data from a single region.
    :param c: new case data for a province or the entire country
    :param d: new death data for a province or the entire country
    :param t: new test results per day data for a province or the entire country
    :param a: updated active cases for the region
    :param h: updated hospitalizations for the region
    :param i: updated ICU patients for the region
    :return:
    """
    c.sort_values(by='day', inplace=True)
    d.sort_values(by='day', inplace=True)
    t.sort_values(by='day', inplace=True)
    a.sort_values(by='day', inplace=True)
    h.sort_values(by='day', inplace=True)
    i.sort_values(by='day', inplace=True)
    s = pd.merge(c, d, how='left', left_on=['day'], right_on=['day'])
    s = pd.merge(s, t, how='left', left_on=['day'], right_on=['day'])
    s = pd.merge(s, a, how='left', left_on=['day'], right_on=['day'])
    s = pd.merge(s, h, how='left', left_on=['day'], right_on=['day'])
    s = pd.merge(s, i, how='left', left_on=['day'], right_on=['day'])

    # drop data prior to start_date, because a lot of the early data isn't very good and
    # plotting those values obscures what's happening now.
    start_date = datetime.strptime("2020-03-15", '%Y-%m-%d')
    s.drop(s[s["day"] < start_date].index, inplace=True)

    s['ncases7day'] = s.cases.rolling(7).mean()
    s['ndeaths7day'] = s.deaths.rolling(7).mean()
    s['nresults7day'] = s.testing.rolling(7).mean()
    s['positiveFraction'] = s.cases / s.testing
    # replace inf and NaN values of positiveFraction with the previous valid value
    s['positiveFraction'].replace(inf, nan, inplace=True)
    s['positiveFraction'].fillna(method='ffill', inplace=True)
    s['pf7day'] = s.positiveFraction.rolling(7).mean()
    s['testing'].clip(-1, inplace=True)  # discard negative numbers of new test results
    s['positiveFraction'].clip(0, 1.0, inplace=True)  # limit positiveFraction to range [0, 1.0]
    s['hosp7day'] = s.TotalHospitalized.rolling(7).mean()
    s['active7day'] = s.TotalActive.rolling(7).mean()
    s['icu7day'] = s.TotalICU.rolling(7).mean()

    prov_pop = {
        'Alberta': 4421876,
        'BC': 5147712,
        'Manitoba': 1379263,
        'NL': 522103,
        'NWT': 45161,
        'New Brunswick': 781476,
        'Nova Scotia': 979351,
        'Nunavut': 39353,
        'Ontario': 14734014,
        'PEI': 159625,
        'Quebec': 8574571,
        'Saskatchewan': 1178681,
        'Yukon': 42052,
        'Canada': 38005238
    }
    s['perCapCases'] = s.cases * 100000 / prov_pop[province]
    s['perCapCases7day'] = s.perCapCases.rolling(7).mean()
    s['perCapDeaths'] = s.deaths * 100000 / prov_pop[province]
    s['perCapDeaths7day'] = s.perCapDeaths.rolling(7).mean()

    s['day'] = s['day'].dt.strftime('%Y-%m-%d')

    return s.to_dict(orient='records')

@app.route('/bc')
@app.route('/dev/bc')
def bc_map():
    # get all case data for BC
    bc_data = pd.read_csv('http://www.bccdc.ca/Health-Info-Site/Documents/BCCDC_COVID19_Dashboard_Case_Details.csv')

    # Aggregate the case data by health region
    bc = bc_data.groupby('Reported_Date').size().reset_index(name='counts')
    bc_sexed = bc_data.groupby(['Reported_Date', 'Sex']).size().reset_index(name='counts')
    bc_aged = bc_data.groupby(['Reported_Date', 'Age_Group']).size().reset_index(name='counts')
    bc_aged_sexed = bc_data.groupby(['Reported_Date', 'Sex', 'Age_Group']).size().reset_index(name='counts')
    bc_ha = bc_data.groupby(['Reported_Date', 'HA']).size().reset_index(name='counts')
    bc_ha_sexed = bc_data.groupby(['Reported_Date', 'HA', 'Sex']).size().reset_index(name='counts')
    bc_ha_aged = bc_data.groupby(['Reported_Date', 'HA', 'Age_Group']).size().reset_index(name='counts')
    bc_ha_aged_sexed = bc_data.groupby(['Reported_Date', 'HA', 'Sex', 'Age_Group']).size().reset_index(name='counts')

    # age bins for aged data
    age_bins = ['<10', '10-19', '20-29', '30-39', '40-49', '50-59', '60-69', '70-79', '80-89', '90+']

    # pivot data so each column is a series of counts, substituting 0 for NaN since no report means a count of 0.
    # bc = bc # no need to pivot this one as it's already a single series
    bc_sexed = bc_sexed.pivot(index=['Reported_Date'], columns=['Sex'], values='counts').fillna(0)
    bc_aged = bc_aged.pivot(index='Reported_Date', columns=['Age_Group'], values="counts").fillna(0)
    bc_aged_sexed = bc_aged_sexed.pivot(index='Reported_Date', columns=['Sex', 'Age_Group'], values="counts").fillna(0)
    bc_ha = bc_ha.pivot(index='Reported_Date', columns=['HA'], values='counts').fillna(0)
    bc_ha_aged = bc_ha_aged.pivot(index='Reported_Date', columns=['HA', 'Age_Group'], values="counts").fillna(0)
    bc_ha_sexed = bc_ha_sexed.pivot(index='Reported_Date', columns=['HA', 'Sex'], values="counts").fillna(0)
    bc_ha_aged_sexed = bc_ha_aged_sexed.pivot(index='Reported_Date', columns=['HA', 'Sex', 'Age_Group'], values="counts").fillna(0)

    # maximum counts for each of the data frames; used to set the y scale when plotting
    max_counts = {
        'bc': max(bc.counts),
        'bc_sexed': bc_sexed.max().max(),
        'bc_aged' : bc_aged.max().max(),
        'bc_aged_sexed': bc_aged_sexed.max().max(),
        'bc_ha' : bc_ha.max().max(),
        'bc_ha_aged': bc_ha_aged.max().max(),
        'bc_ha_sexed': bc_ha_sexed.max().max(),
        'bc_ha_aged_sexed': bc_ha_aged_sexed.max().max()
    }

    bc = bc.to_csv()
    bc_aged = bc_aged.to_csv()
    bc_ha = bc_ha.to_csv()
    bc_ha_aged = bc_ha_aged.to_csv()

    # render the HTML file and save it to S3
    rendered = render_template("bc.html", age_bins= age_bins, max_counts=max_counts, bc_aged=bc_aged, bc_ha=bc_ha)
    write_html_to_s3(rendered, "bc.html", "covid.pacificloon.ca")

    # return an HTTP redirect to the static file in S3
    return "<html><head><meta http-equiv=\"Refresh\" content=\"0; URL=http://covid.pacificloon.ca/bc.html\"></head><body><p>Updated bc.html</p></body></html>"

def write_html_to_s3(content, filename, bucket):
    """ Write an html file to an S3 bucket"""

    # Create S3 object
    s3_resource = boto3.resource("s3")

    # Write buffer to S3 object
    s3_resource.Object(bucket, f'{filename}').put(
        Body=content, ContentType="text/html", ACL="public-read"
    )

if __name__ == '__main__':
    app.run()
