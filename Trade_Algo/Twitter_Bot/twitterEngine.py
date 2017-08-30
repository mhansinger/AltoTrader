import numpy as np
import pandas as pd
import tweepy as tw
import random as rnd

# reads in the keys

#from twitter_keys import *
# im trader ist das alles unter Twitter_Bot abgelegt
from Twitter_Bot.twitter_keys import *

class twitterEngine(object):

    def __init__(self):
        self.auth = tw.OAuthHandler(consumer_key, consumer_secret)
        self.auth.set_access_token(access_token, access_token_secret)
        self.api = tw.API(self.auth)

    def good_tweet(self):
        from Twitter_Bot.good_tweets import good_tweets
        length = len(good_tweets)
        # generate random number
        n = rnd.randrange(0, length - 1)
        # choose a tweet
        this_tweet = good_tweets[n]
        # sends the tweet!
        self.api.update_status(this_tweet)
        print(this_tweet+'\n')

    def bad_tweet(self):
        from Twitter_Bot.bad_tweets import bad_tweets
        length = len(bad_tweets)
        # generate random number
        n = rnd.randrange(0, length - 1)
        # choose a tweet
        this_tweet = bad_tweets[n]
        # sends the tweet!
        self.api.update_status(this_tweet)
        print(this_tweet+'\n')






