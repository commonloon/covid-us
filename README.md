# covid-us
A flask app to plot covid new case data for all US states; expanded to plot data for other regions.

NOTE: this app generates static HTML files that are served from an AWS bucket; it does not serve the data directly.

I don't want to pay for an EC2 instance to host the web app, so I run the app on a 
Rasperry Pi Zero W running Raspbian.  Cron jobs poke the endpoints periodically to make the web app
update the html files in the AWS S3 bucket that serves the files to http://covid.pacificloon.ca
for public consumption.

I created this app as an exercise to help me learn to use the d3 javascript library.

This is a personal project, which I tinker with as I have time and inclination.  Feel free to file issues; I'll take them into account when I prioritize new work.

Why is this a web app and not a script?  It's due to how the code evolved.  Originally the web app served the 
plots directly. That proved to be slow and a waste of other people's resources.  I adopted the current 
approach when I converted the app to run as an AWS Lambda function.  Eventually the size of the required 
python libraries exceeded an AWS size limit and I moved the app to a Rasperry Pi Zero W in my house.
A cron job on the rpi pokes the app endpoints at appropriate times to update the static html files.

If I were starting from scratch, I would write a command line script which takes appropriate arguments
instead of using web app, but for now it's easier not to convert.

I'm running Flask under nginx following the instructions at
https://www.raspberrypi-spy.co.uk/2018/12/running-flask-under-nginx-raspberry-pi/

The uwsgi.ini file is included in the repo.

I used "apt install awscli" to install the AWS CLI, then ran "aws configure" as user "pi" to set up the configuration file.
The web server runs as www-data, so I ran "sudo (cp -r ~pi/.aws /var/www; chown -Rh www-data.www-data /var/www/.aws)"
to install the permissions where the flask app can find them.

Something needs to poke the web endpoints periodically in order to update the static files in S3;
I use cron for this and have checked in my crontab file.
