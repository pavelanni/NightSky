# coding=utf-8

# Sky Guide
# By Pavel Anni <pavel.anni@gmail.com>
#
# An Alexa Skill which tells you where are planets in the sky

import logging
import boto3
import math
import maya
import ephem
from ephem import cities
from timezonefinder import TimezoneFinder
from datetime import datetime
from flask import Flask, json, render_template
from flask_ask import Ask, request, session, context, question, statement
from flask_ask import delegate
from boto3.dynamodb.conditions import Key, Attr
from botocore.exceptions import ClientError
from geopy.geocoders import Nominatim

__author__ = 'Pavel Anni'
__email__ = 'pavel.anni@gmail.com'

users_table = 'user_locations'

app = Flask(__name__)
ask = Ask(app, '/')
logging.getLogger("flask_ask").setLevel(logging.DEBUG)


def city_tz(city):
    tf = TimezoneFinder()
    try:
        city_location = cities.lookup(city)
    except ValueError:
    #    raise
        return None
    tz = tf.timezone_at(lng=math.degrees(city_location.lon),
                        lat=math.degrees(city_location.lat))

    return tz


def city_latlon(city):
    geolocator = Nominatim(user_agent="Lambda")
    location = geolocator.geocode(city)

    return (location.latitude, location.longitude)


def where_is_planet(planet, time):
    observer = ephem.Observer()
    observer.lat = session.attributes['lat']
    observer.lon = session.attributes['lon']
    observer.date = time
    p = getattr(ephem, planet)()
    p.compute(observer)
    pos = (round(math.degrees(p.az)), round(math.degrees(p.alt)))

    return pos


def create_user(user_id, user_city):
    user_tz = city_tz(user_city)
    (lat, lon) = city_latlon(city)
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(users_table)

    response = table.put_item(
        Item={
            'user_id': user_id,
            'user_city': user_city,
            'user_tz': user_tz,
            'lat': str(round(lat)),
            'lon': str(round(lon)),
        })

    return

def set_user_city():
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(users_table)
    user_id = context.System.user.userId

    table.update_item(
        Key={
            'user_id': user_id,
        },
        UpdateExpression="SET user_city=:c, user_tz=:t, lat=:a, lon=:o",
        ExpressionAttributeValues={
            ':c': session.attributes['city'],
            ':t': session.attributes['tz'],
            ':a': session.attributes['lat'],
            ':o': session.attributes['lon'],
        },
        ReturnValues='UPDATED_NEW')

    return

def load_user_city():
    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(users_table)
    user_id = context.System.user.userId

    try:
        response = table.get_item(
            Key={
                'user_id': user_id,
            }
        )
    except ClientError as e:
        print(e.response['Error']['Message'])
        return None

    if 'Item' in response:
        item = response['Item']
        session.attributes['city'] = item['user_city']
        session.attributes['tz'] = item['user_tz']
        session.attributes['lat'] = item['lat']
        session.attributes['lon'] = item['lon']
        return item['user_city']
    else:
        return None

# We need this for slot that are required and involve futher dialog
# described here: https://stackoverflow.com/questions/48053778/how-to-create-conversational-skills-using-flask-ask-amazon-alexa-and-python-3-b
def get_dialog_state():
    return session['dialogState']

@ask.intent('SetLocationIntent')
def set_location(city):
    tz = city_tz(city)
    (lat, lon) = city_latlon(city)
    session.attributes['city'] = city
    session.attributes['tz'] = tz
    session.attributes['lat'] = str(round(lat))
    session.attributes['lon'] = str(round(lon))

    dynamodb = boto3.resource('dynamodb')
    table = dynamodb.Table(users_table)
    user_id = context.System.user.userId

    try:
        response = table.get_item(
            Key={
                'user_id': user_id,
            }
        )
        set_user_city()    # user_id, city and tz are already in session.attributes
    except ClientError as e:
        create_user(user_id, city)

    text = f"Your location is set to {city}. Now ask me about planets."

    return question(text).standard_card(title="Sky Guide", text=text)


@ask.intent('PlanetIntent', default={'date': 'today'})
def planet_intent(planet, time, date):
    dialog_state = get_dialog_state()
    if dialog_state != 'COMPLETED':
        return delegate()

    utc_time = maya.when(' '.join([date, time]),
                         session.attributes['tz']).datetime()
    pos = where_is_planet(planet, utc_time)

    if pos[1] <=0:
        text = (f"Unfortunately, {planet} is below the horizon at that moment "
                  "in your location.")
    else:
        text = (f"At that moment {planet} is located at "
                  f"azimuth {pos[0]} degrees, elevation {pos[1]} degrees")

    return statement(text).standard_card(title="Sky Guide", text=text)


# Session starter
#
# This intent is fired automatically at the point of launch (= when the session starts).
# Use it to register a state machine for things you want to keep track of, such as what the last intent was, so as to be
# able to give contextual help.

@ask.on_session_started
def start_session():
    """
    Fired at the start of the session, this is a great place to initialise state variables and the like.
    """
    logging.debug("Session started at {}".format(datetime.now().isoformat()))

    session.attributes['user_id'] = context.System.user.userId
    user_city = load_user_city()

    return

# Launch intent
#
# This intent is fired automatically at the point of launch.
# Use it as a way to introduce your Skill and say hello to the user. If you envisage your Skill to work using the
# one-shot paradigm (i.e. the invocation statement contains all the parameters that are required for returning the
# result

@ask.launch
def handle_launch():
    """
    (QUESTION) Responds to the launch of the Skill with a welcome statement and a card.

    Templates:
    * Initial statement: 'welcome'
    * Reprompt statement: 'welcome_re'
    * Card title: 'Sky Guide'
    * Card body: 'welcome_card'
    """

    user_city = load_user_city()
    if user_city:                   # user in the database and location is set
        welcome_text = render_template('welcome',
                                       city=session.attributes['city'])
        welcome_re_text = render_template('welcome_re')
        welcome_card_text = render_template('welcome_card')
    else:
        welcome_text = render_template('welcome_new')
        welcome_re_text = render_template('welcome_new_re')
        welcome_card_text = render_template('welcome_card')


    return question(welcome_text).reprompt(welcome_re_text).standard_card(title="Sky Guide",
                                                                          text=welcome_card_text)


# Built-in intents
#
# These intents are built-in intents. Conveniently, built-in intents do not need you to define utterances, so you can
# use them straight out of the box. Depending on whether you wish to implement these in your application, you may keep
# or delete them/comment them out.
#
# More about built-in intents: http://d.pr/KKyx

@ask.intent('AMAZON.StopIntent')
def handle_stop():
    """
    (STATEMENT) Handles the 'stop' built-in intention.
    """
    farewell_text = render_template('stop_bye')
    return statement(farewell_text)


@ask.intent('AMAZON.CancelIntent')
def handle_cancel():
    """
    (STATEMENT) Handles the 'cancel' built-in intention.
    """
    farewell_text = render_template('cancel_bye')
    return statement(farewell_text)


@ask.intent('AMAZON.HelpIntent')
def handle_help():
    """
    (QUESTION) Handles the 'help' built-in intention.

    You can provide context-specific help here by rendering templates conditional on the help referrer.
    """

    help_text = render_template('help_text')
    return question(help_text)


@ask.intent('AMAZON.NoIntent')
def handle_no():
    """
    (?) Handles the 'no' built-in intention.
    """
    pass

@ask.intent('AMAZON.YesIntent')
def handle_yes():
    """
    (?) Handles the 'yes'  built-in intention.
    """
    pass


@ask.intent('AMAZON.PreviousIntent')
def handle_back():
    """
    (?) Handles the 'go back!'  built-in intention.
    """
    pass

@ask.intent('AMAZON.StartOverIntent')
def start_over():
    """
    (QUESTION) Handles the 'start over!'  built-in intention.
    """
    pass


# Ending session
#
# This intention ends the session.

@ask.session_ended
def session_ended():
    """
    Returns an empty for `session_ended`.

    .. warning::

    The status of this is somewhat controversial. The `official documentation`_ states that you cannot return a response
    to ``SessionEndedRequest``. However, if it only returns a ``200/OK``, the quit utterance (which is a default test
    utterance!) will return an error and the skill will not validate.

    """
    return statement("")


if __name__ == '__main__':
    app.run(debug=True)
