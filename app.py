from flask import Flask, render_template, url_for, request
import pandas as pd
from numpy import nanmax, inf, nan
import boto3
from datetime import datetime
import requests
from urllib.parse import urljoin

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

@app.route('/us')
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

    states_pop = {row[0]: row[1] for _, row in \
                  pd.read_csv(urljoin(request.base_url,url_for("static", filename="US_2020_pop_estimates.csv"))).iterrows()}

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

def plot_regional_dataset(df, countries, output_filename, last_day,
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
        try:
            s = df.loc[df.country == country, ['day',
                                              'cases', 'deaths',
                                              'percapCases', 'percapDeaths',
                                              'ncases7day', 'ndeaths7day',
                                              'percapCases7day', 'percapDeaths7day']]
        except Exception as e:
            print(e)
            raise e
        s.sort_values(by='day', inplace=True)

        s['totalTestResultsIncrease'] = 0
        s['positiveFraction'] = 0
        s['nresults7day'] = 0
        s['pf7day'] = 0

        data[country] = s.to_dict(orient='records')

    # render the HTML file and save it to S3
    rendered = render_template("world.html",
                               countries=countries,
                               data=data,
                               last_day=last_day,
                               title=title,
                               headline=headline,
                               source_data_url=source_data_url)
    write_html_to_s3(rendered, output_filename, "covid.pacificloon.ca")

def plot_worldwide_totals(df, last_day, title, headline, source_data_url):
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


def plot_vaccinations(df, countries, output_filename,
                          title,
                          headline,
                          source_data_url):
    """

    :param df: dataframe containing the relevant data
    :param countries: list of countries to plot
    :param output_filename: name of the resulting HTML file in the S3 bucket
    :param last_day: day when the source data was last updated
    :param max_per_capita: used to set a fixed scale for plots of per capita data, so countries compare easily
    :return:
    """
    last_day = max(df.day)
    data = {}
    for country in countries:
        try:
            s = df.loc[df.country == country, ['day',
                                              'daily_doses', 'total_doses',
                                              'percapDailyDoses', 'dailyDoses7day',
                                              'percapTotalDoses', 'percapDailyDoses7day']]
        except Exception as e:
            print(e)
            raise e
        s.sort_values(by='day', inplace=True)

        data[country] = s.to_dict(orient='records')

    # render the HTML file and save it to S3
    rendered = render_template("jab.html",
                               countries=countries.tolist(),
                               data=data,
                               last_day=last_day,
                               title=title,
                               headline=headline,
                               source_data_url=source_data_url)
    write_html_to_s3(rendered, output_filename, "covid.pacificloon.ca")


def munge_vaccine_data(pop):
    """
    Get cumulative COVID vaccination data from disease.sh and process it to get per-day values
    :return:
    """
    source_url = 'https://disease.sh/v3/covid-19/vaccine/coverage/countries?lastdays=365'

    header = {
        "User-Agent":
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.75 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest"
    }

    r = requests.get(source_url, headers=header)

    # make a dataframe of the case data
    df = pd.read_json(r.text)
    countries = df.country.unique()

    data = None
    for country in countries:
        country_data = None
        s = df[df.country == country]
        p = pop[pop.region == country]
        try:
            pop100k = p.pop2019.iloc(0)[0] / 100000.0  # country population in hundred thousands
        except Exception as e:
            # skip regions for which I don't have population data in my file (derived from the ECDC data).
            # I could find population data for these regions, but they're not ones I care about plotting
            continue

        try:
            # v is the cumulative total of vaccine doses delivered
            v = pd.Series(s[s.country == country].timeline.iloc(0)[0], name='total_doses')
            daily = v.diff().rename('daily_doses')
            daily.drop(daily.index[0], inplace=True) # first value is always a NaN
            v.drop(v.index[0], inplace=True) # match length of daily series
            country_data = pd.merge(v, daily, left_index=True, right_index=True)

            # add the day as a column in a sortable string format
            country_data['day'] = country_data.index
            country_data['day'] = pd.to_datetime(country_data['day'].apply(str), dayfirst=False)
            country_data['day'] = country_data['day'].dt.strftime('%Y-%m-%d')

            # add in the country name and compute moving averages
            country_data['country'] = country
            try:
                country_data['percapTotalDoses'] = country_data.total_doses / pop100k
                country_data['percapDailyDoses'] = country_data.daily_doses / pop100k
                country_data['dailyDoses7day'] = country_data.daily_doses.rolling(7).mean()
                country_data['percapDailyDoses7day'] = country_data.percapDailyDoses.rolling(7).mean()
            except Exception as e:
                print(country + ' ' + str(e))
                continue  # skip countries that throw errors
        except Exception as e:
            print(country + ' ' + str(e))
            continue
        pass

        # append the data for this country to the main dataframe
        if data is None:
            data = country_data
        else:
            data = data.append(country_data)

    # The first few days of the 7 day moving averages will typically be NaN, but it
    # should be fine to set them to zero
    data['dailyDoses7day'].replace(inf, nan, inplace=True)
    data['percapDailyDoses7day'].replace(inf, nan, inplace=True)

    plot_vaccinations(data, countries, "jabs.html", "Vaccinations", "Vaccination Status", source_url)

    return


@app.route('/world')
def world():
    # get 2019 population estimates for all countries
    pop = pd.read_csv(urljoin(request.base_url, url_for('static', filename='2019_pop.csv')))

    # get and process data on vaccinations
    munge_vaccine_data(pop)

    # read the data source
    url = 'https://disease.sh/v3/covid-19/historical?lastdays=365'

    header = {
        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/50.0.2661.75 Safari/537.36",
        "X-Requested-With": "XMLHttpRequest"
    }

    r = requests.get(url, headers=header)

    # make a dataframe of the case data
    df = pd.read_json(r.text)
    countries = df.country.unique()

    data = None
    for country in countries:
        country_data = None
        s = df[df.country == country]
        p = pop[pop.region == country]
        try:
            pop100k = p.pop2019.iloc(0)[0] / 100000.0  # country population in hundred thousands
        except Exception as e:
            # skip regions for which I don't have population data in my file (derived from the ECDC data).
            # I could find population data for these regions, but they're not ones I care about plotting
            continue
        provinces = s.province.to_list()

        # for some European countries (e.g. Denmark, France and UK), the data source sets the province to None
        # for the main country and sets the province value when giving data for overseas territories.
        # This is inconsistent with how the field is used for e.g. Canada or Australia, where there is no entry
        # for the main country and the main country data has to be summed from the values for its provinces.
        if len(provinces) > 1 and None in provinces:
            s.province = s.province.replace(to_replace=[None], value=country)

        # sum the province case data to get totals for each country.  If the province is None, assume the data is
        # for the entire country.
        for prov in s.province.to_list():
            if prov is None:
                try:
                    c = pd.Series(s[s.country == country].timeline.iloc(0)[0]['cases'], name='cases')
                    d = pd.Series(s[s.country == country].timeline.iloc(0)[0]['deaths'], name='deaths')
                    r = pd.Series(s[s.country == country].timeline.iloc(0)[0]['recovered'], name='recovered')

                    tmp_data = pd.merge(pd.merge(c, d, left_index=True, right_index=True),
                                            r, left_index=True, right_index=True)
                    daily = tmp_data.diff()
                    daily.drop(daily.index[0], inplace=True)
                    daily = daily.astype({'cases':'int32', 'deaths': 'int32', 'recovered': 'int32'})
                    tmp_data['day'] = tmp_data.index
                    tmp_data['day'] = pd.to_datetime(tmp_data['day'].apply(str), dayfirst=False)
                    tmp_data['day'] = tmp_data['day'].dt.strftime('%Y-%m-%d')
                    daily = pd.merge(daily, tmp_data.day, left_index=True, right_index=True)
                    country_data = daily
                except Exception as e:
                    raise e
            else:
                c = pd.Series(s[s.province == prov].timeline.iloc(0)[0]['cases'], name='cases')
                d = pd.Series(s[s.province == prov].timeline.iloc(0)[0]['deaths'], name='deaths')
                r = pd.Series(s[s.province == prov].timeline.iloc(0)[0]['recovered'], name='recovered')
                prov_data = pd.merge(pd.merge(c, d, left_index=True, right_index=True),
                                        r, left_index=True, right_index=True)
                daily = prov_data.diff()
                daily.drop(daily.index[0], inplace=True)
                daily = daily.astype({'cases':'int32', 'deaths': 'int32', 'recovered': 'int32'})
                prov_data['day'] = prov_data.index
                prov_data['day'] = pd.to_datetime(prov_data['day'].apply(str), dayfirst=False)
                prov_data['day'] = prov_data['day'].dt.strftime('%Y-%m-%d')
                daily = pd.merge(daily, prov_data.day, left_index=True, right_index=True)

                if country_data is None:
                    country_data = daily
                else:
                    country_data.cases += daily.cases
                    country_data.deaths += daily.deaths
                    country_data.recovered += daily.recovered

        # set negative deaths to zero, on the assumption these are data errors.
        # Some may be valid corrections to data, but in most cases setting them to zero won't
        # affect the overall picture for the country.
        country_data.loc[(country_data.cases < 0), 'cases'] = 0
        country_data.loc[(country_data.deaths < 0), 'deaths'] = 0

        # add in the country name and compute moving averages
        country_data['country'] = country
        try:
            country_data['percapCases'] = country_data.cases / pop100k
            country_data['percapDeaths'] = country_data.deaths / pop100k
            country_data['ncases7day'] = country_data.cases.rolling(7).mean()
            country_data['ndeaths7day'] = country_data.deaths.rolling(7).mean()
            country_data['percapCases7day'] = country_data.ncases7day / pop100k
            country_data['percapDeaths7day'] = country_data.ndeaths7day / pop100k
        except Exception as e:
            print(e)
            continue  # skip countries that throw errors

        # append the data for this country to the main dataframe
        if data is None:
            data = country_data
        else:
            data = data.append(country_data)

        last_day = max(data.day)

    # Fix problem with new case value for December 10th in Turkey.
    # Doing the fix here means the 7 day moving average is still messed up, but at least the chart uses a better scale.
    data.loc[(data['country'] == 'Turkey') & (data['day'] == '2020-12-10'), 'cases'] = 0

    # plot the worldwide totals
    plot_worldwide_totals(data, last_day,
                          title='Worldwide Covid Cases',
                          headline="Sum of all the individual country data.",
                          source_data_url=url)

    # select the countries to plot for each region.
    # There's no particular reason for choosing these countries, other than I was interested in
    # seeing the corresponding charts.
    #europe = sorted(['France', 'Germany', 'Denmark', 'Spain', 'Greece', 'Italy',
    #                 'UK', 'Netherlands', 'Poland', 'Estonia', 'Latvia',
    #                 'Russia', 'Norway', 'Sweden', 'Switzerland', 'Belgium', 'Hungary', 'Romania',
    #                 'Croatia', 'Austria', 'Belarus', 'Czechia', 'Ukraine', 'Ireland', 'Finland',
    #                 'Iceland', 'Bulgaria', 'Malta', 'Serbia', 'Bosnia', 'Cyprus', 'Albania',
    #                 'Slovenia', 'Slovakia', 'Moldova', 'Kosovo', "Portugal"])
    europe = sorted(["Albania", "Andorra", "Armenia", "Austria", "Azerbaijan",
                    "Belarus", "Belgium", "Bosnia", "Bulgaria", "Croatia",
                    "Cyprus", "Czechia", "Denmark", "Estonia", "Finland", "France",
                     "Georgia", "Germany", "Greece", "Hungary", "Iceland",
                    "Ireland", "Italy", "Kosovo","Latvia", "Liechtenstein", "Lithuania",
                     "Luxembourg", "Malta",
                    "Moldova", "Montenegro", "Netherlands",
                    "Macedonia", "Norway", "Poland", "Portugal", "Romania",
                    "Russia", "San Marino", "Serbia", "Slovakia", "Slovenia",
                    "Spain", "Sweden", "Switzerland", "Ukraine", "UK"
                    ])
#    asia = sorted(['China', 'India', 'Pakistan', 'Bangladesh', 'Thailand', 'Burma', 'Indonesia',
#                   'Malaysia', 'Australia', 'New Zealand', 'Mongolia', 'Afghanistan', 'Iran', 'Turkey',
#                   'Israel', 'Jordan', 'Saudi Arabia', 'S. Korea', 'Philippines', 'Singapore'])
    asia = sorted(["Afghanistan", "Bahrain", "Bangladesh", "Bhutan", "Brunei",
                    "Burma", "Cambodia", "China", "India", "Indonesia", "Iran",
                    "Iraq", "Israel", "Japan", "Jordan", "Kazakhstan", "Kuwait",
                    "Kyrgyzstan", "Lebanon",
                    "Malaysia", "Maldives", "Mongolia", "Nepal",
                    "Oman", "Pakistan", "Philippines", "Qatar",
                    "Saudi Arabia", "Singapore", "S. Korea", "Sri Lanka",
                    "Syrian Arab Republic", "Taiwan", "Tajikistan", "Thailand",
                    "Turkey", "UAE", "Uzbekistan", "Vietnam", "Yemen"
                    ])
    #africa = sorted(['Ethiopia', 'Sudan', 'Congo', 'Nigeria', 'Morocco', 'Ghana', 'South Africa',
    #                'Kenya', 'Egypt', 'Libyan Arab Jamahiriya', 'Tunisia', 'Algeria', 'Namibia', 'Uganda'])
    africa = sorted(["Algeria", "Angola", "Benin", "Botswana", "Burkina Faso", "Burundi",
                    "Cameroon", "Cabo Verde", "Central African Republic", "Chad", "Comoros",
                    "Congo", "DRC",
                    "Djibouti", "Egypt", "Equatorial Guinea", "Eritrea",
                    "Ethiopia", "Gabon", "Gambia", "Ghana", "Guinea", "Guinea-Bissau",
                    "Kenya", "Lesotho", "Liberia", "Libyan Arab Jamahiriya",
                    "Madagascar", "Malawi", "Mali", "Mauritania", "Mauritius", "Morocco",
                    "Mozambique", "Namibia", "Niger", "Nigeria", "Rwanda",
                    "Sao Tome and Principe", "Senegal", "Seychelles", "Sierra Leone",
                    "Somalia", "South Africa", "South Sudan", "Sudan",
                    "Togo", "Tunisia", "Uganda",
                    "Zambia", "Zimbabwe"])
    #americas = sorted(['Canada', 'USA', 'Mexico', 'Brazil', 'Chile', 'Argentina',
    #                   'Guatemala', 'Costa Rica', 'Haiti', 'Cuba', 'Venezuela', 'Colombia', 'Bolivia',
    #                   'Peru', 'Uruguay', 'Paraguay', 'Belize', 'Jamaica'])
    americas = sorted(["Argentina", "Bahamas", "Barbados", "Belize",
                        "Bolivia", "Brazil", "Canada",
                        "Chile", "Colombia", "Costa Rica", "Cuba", "Dominican Republic",
                        "Ecuador", "El Salvador", "Grenada", "Guatemala", "Guyana",
                        "Haiti", "Honduras", "Jamaica", "Mexico",
                        "Nicaragua", "Panama", "Paraguay", "Peru",
                        "Trinidad and Tobago",
                        "USA", "Uruguay", "Venezuela"
                        ])

    plot_regional_dataset(data, asia, 'asia.html', last_day,
                          title='Asian Covid Charts',
                          headline="Covid Data for an arbitrary subset of Asian and Polynesian countries",
                          source_data_url=url)
    plot_regional_dataset(data, africa, 'africa.html', last_day,
                          title='African Covid Charts',
                          headline="Covid Data for an arbitrary subset of African countries",
                          source_data_url=url)
    plot_regional_dataset(data, americas, 'americas.html', last_day,
                          title='Americas Covid Charts',
                          headline="Covid Data for an arbitrary subset of countries in the Americas",
                          source_data_url=url)
    plot_regional_dataset(data, europe, 'europe.html', last_day,
                          title='European Covid Charts',
                          headline="Covid Data for an arbitrary subset of European countries",
                          source_data_url=url)

    # return an HTTP redirect to the static file in S3
    return "<html><head><meta http-equiv=\"Refresh\" content=\"0; URL=http://covid.pacificloon.ca/europe.html\"></head><body><p>Updated europe.html</p></body></html>"


@app.route('/')
@app.route('/canada')
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

    # vaccination data
    v_received = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/vaccine_distribution_timeseries_prov.csv')
    v_administered= pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/vaccine_administration_timeseries_prov.csv')
    v_completed = pd.read_csv('https://raw.githubusercontent.com/ishaberry/Covid19Canada/master/timeseries_prov/vaccine_completion_timeseries_prov.csv')
    v_received['day'] = pd.to_datetime(v_received['date_vaccine_distributed'].apply(str),dayfirst=True)
    v_administered['day'] = pd.to_datetime(v_administered['date_vaccine_administered'].apply(str),dayfirst=True)
    v_completed['day'] = pd.to_datetime(v_completed['date_vaccine_completed'].apply(str),dayfirst=True)

    # get hospitalization data
    arcgis = pd.read_csv('https://opendata.arcgis.com/datasets/3afa9ce11b8842cb889714611e6f3076_0.csv')
    #arcgis['day'] = pd.to_datetime(arcgis['SummaryDate'].apply(str),
    #                               dayfirst=False, format="%Y/%m/%d", utc=True).dt.tz_convert(None)
    arcgis['day'] = pd.to_datetime(arcgis['SummaryDate'].apply(str),
                                   dayfirst=False, format="%Y/%m/%d", utc=True)
    arcgis['day'] = arcgis.day.dt.tz_convert(None)
    arcgis.day -= pd.Timedelta(hours=12)

    # most recent day on which the data was updated
    last_day = max(cases.day).strftime("%Y-%m-%d")
    arcgis_last_day = max(arcgis.day).strftime("%Y-%m-%d")

    # get ICU capacity
    icu_beds = {row[1]: int(row[3].replace(',', '')) for _, row in pd.read_csv(urljoin(request.base_url,url_for("static", filename="canada_icu_beds.csv"))).iterrows()}

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
    }
    prov_plus_map = prov_map.copy()
    prov_plus_map['Canada'] = 'Canada'

    # population data by region
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

    data = {}
    vaccine_data = {}
    for prov in provinces:
        arcgis_abbrev = prov_plus_map[prov]
        c = cases.loc[cases.province == prov, ['day', 'cases']]
        d = deaths.loc[deaths.province == prov, ['day', 'deaths']]
        t = tests.loc[tests.province == prov, ['day', 'testing']]
        a = arcgis.loc[arcgis.Abbreviation == arcgis_abbrev, ['day', 'TotalActive']]
        h = arcgis.loc[arcgis.Abbreviation == arcgis_abbrev, ['day', 'TotalHospitalized']]
        i = arcgis.loc[arcgis.Abbreviation == arcgis_abbrev, ['day', 'TotalICU']]
        vr = v_received[v_received.province == prov][['day', 'dvaccine', 'cumulative_dvaccine']].copy()
        va = v_administered[v_administered.province == prov][['day', 'avaccine', 'cumulative_avaccine']].copy()
        vc = v_completed[v_completed.province == prov][['day', 'cvaccine', 'cumulative_cvaccine']].copy()
        data[prov_map[prov]] = canada_to_dict(prov, prov_pop[prov], c, d, t, a, h, i)
        vaccine_data[prov_map[prov]] = canada_vaccine_to_dict(prov, prov_pop[prov], vr, va, vc)
        pass

    # add the national data
    data[prov_plus_map['Canada']] = canada_to_dict('Canada', prov_pop['Canada'],
                                              national_cases.filter(['day', 'cases'], axis=1),
                                              national_deaths.filter(['day', 'deaths'], axis=1),
                                              national_tests.filter(['day', 'testing'], axis=1),
                                              arcgis.loc[arcgis.Abbreviation == 'CA', ['day', 'TotalActive']],
                                              arcgis.loc[arcgis.Abbreviation == 'CA', ['day', 'TotalHospitalized']],
                                              arcgis.loc[arcgis.Abbreviation == 'CA', ['day', 'TotalICU']]
                                              )
    # render the HTML file and save it to S3
    rendered = render_template("canada.html", provinces=sorted(prov_plus_map.values()), data=data,
                               last_day=last_day, arcgis_last_day=arcgis_last_day, icu_beds=icu_beds)
    write_html_to_s3(rendered, "canada.html", "covid.pacificloon.ca")

    # render the vaccine data HTML file and save it to S3
    rendered = render_template("jab_canada.html", regions=sorted(prov_map.values()), data=vaccine_data,
                               last_day=max(v_administered.day).strftime("%Y-%m-%d"))
    write_html_to_s3(rendered, "jab_canada.html", "covid.pacificloon.ca")


    # return an HTTP redirect to the static file in S3
    return "<html><head><meta http-equiv=\"Refresh\" content=\"0; URL=http://covid.pacificloon.ca/canada.html\"></head><body><p>Updated canada.html</p></body></html>"

def canada_vaccine_to_dict(province, prov_pop, vr, va, vc):
    """

    :param province:
    :param vr: vaccines received
    :param va: doses administered
    :param vc: vaccinations completed
    :return:
    """
    vr.sort_values(by='day', inplace=True)
    va.sort_values(by='day', inplace=True)
    vc.sort_values(by='day', inplace=True)

    # merge into a single dataframe
    s = pd.merge(vr, va, how='left', left_on=['day'], right_on=['day'])
    s = pd.merge(s,  vc, how='left', left_on=['day'], right_on=['day'])

    # compute per capita
    s['dosesPer100pop'] = 100.0 * s.cumulative_avaccine / prov_pop
    s['completedPer100pop'] = 100.0 * s.cumulative_cvaccine / prov_pop

    # scale the graphs appropriately by lying about the zeroth entry
    s['dosesPer100pop'].iloc[0] = 25
    s['completedPer100pop'].iloc[0] = 25

    # compute any 7 day averages
    s['admin7day'] = s.avaccine.rolling(7).mean()
    s['completed7day'] = s.cvaccine.rolling(7).mean()

    # Replace NaN values with zero
    s.fillna(value=0, inplace=True)

    # convert the date to a string in a sortable format
    s['day'] = s['day'].dt.strftime('%Y-%m-%d')

    return s.to_dict(orient='records')


def canada_to_dict(province, prov_pop, c, d, t, a, h, i):
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

    s['perCapCases'] = s.cases * 100000 / prov_pop
    s['perCapCases7day'] = s.perCapCases.rolling(7).mean()
    s['perCapDeaths'] = s.deaths * 100000 / prov_pop
    s['perCapDeaths7day'] = s.perCapDeaths.rolling(7).mean()

    s['day'] = s['day'].dt.strftime('%Y-%m-%d')

    return s.to_dict(orient='records')

@app.route('/bc')
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
