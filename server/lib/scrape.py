import logging

from api.models import Image, TwitterUser as UserModel
from django.db import IntegrityError
from django.utils import timezone
from lib.twitter import TwitterAPI, TwitterMediaType, TwitterUser as APIUser

logger = logging.getLogger(__name__)


class Scraper:
    api: TwitterAPI

    def __init__(self, token: str):
        self.api = TwitterAPI(token)

    def scrape_timeline(self, count: int, username: str = None, twitter_id: str = None):
        """
        Scrapes a user's timeline for images and adds them to the database.

        `username` or `twitter_id` must be given, but not both.

        Returns a 3-tuple with some stats from the scrape:
            - The number of tweets retrieved
            - The number of images found
            - The number of images that were missing and added to the database
        """
        if count < TwitterAPI.MIN_RESULTS_LIMIT:
            raise ValueError(f"Count must be at least 1.")

        user, created_user = self._get_user_object(username, twitter_id)

        if created_user:
            logger.debug("Created new user")
        else:
            logger.debug("Found existing user in database")

        # Set this early to try and mitigate simultaneous fetch requests
        user.last_scraped_at = timezone.now()
        user.save()

        logger.info(f"Scrape start")

        tweets = self.api.get_user_media_tweets_auto_paginate(u.id, limit=count)
        logger.debug(f"Found {len(tweets)} tweets")

        if not tweets:
            return

        images = []

        for t in tweets:
            for m in t.media:
                if m.type != TwitterMediaType.Photo:
                    continue

                images.append(
                    Image(
                        key=m.key,
                        tweet_id=t.tweet_id,
                        url=m.url,
                        user=user,
                        tweeted_at=t.created_at,
                    )
                )

        logger.debug(f"Found {len(images)} images")

        added = 0

        for obj in images:
            try:
                obj.save()
                added += 1
            except IntegrityError:
                pass

        logger.debug(f"Added {added} new images")
        logger.info("Scrape end")

        return (len(tweets), len(images), added)

    def _get_user_object(self, username: str = None, twitter_id: str = None):
        """
        Gets the user object for the given `username` or `twitter_id`.

        Exactly one argument must be given.

        If the user does not exist in the database, this retrieves their info and
        adds the new user.

        Returns a 2-tuple (user, created), where `created` is True if the user
        was just added.
        """
        if not username and not twitter_id:
            raise ValueError("Username or Twitter ID must be given.")
        elif username and twitter_id:
            raise ValueError("Only the username or Twitter ID can be given, not both.")

        created = False
        user: UserModel

        if username:
            try:
                user = UserModel.objects.get(username__iexact=username)
            except UserModel.DoesNotExist:
                data = self.api.get_user_by_username(username)
                user = UserModel(
                    profile_image_url=data.profile_image_url,
                    twitter_id=data.id,
                    username=data.username,
                )
                user.save()
                created = True
        else:
            # Making the assumption that the user exists if we know their Twitter ID
            user = UserModel.objects.get(twitter_id=twitter_id)

        return (user, created)
