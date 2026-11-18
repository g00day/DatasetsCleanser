from django.db import models
from django.conf import settings

from django.contrib.auth.models import AbstractUser

import datetime

import uuid

import jwt


class Account(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, unique=True, editable=False)
    email = models.EmailField(max_length=256, unique=True, verbose_name="Email address")
    username = models.CharField(max_length=45, unique=True, verbose_name="Username")
    avatar = models.ImageField(upload_to='bakot/static/bakot/imagination', height_field=None, width_field=None, blank=True, null=True, verbose_name="Profile picture")
    created_at = models.DateTimeField(auto_now_add=True, editable=False, verbose_name="Registration time")
    updated_at = models.DateTimeField(null=True, verbose_name="Updated at")

    def __str__(self):
        return self.username
    
    @property
    def get_token(self):
        """
        Allows you to get a user token by calling user.token, instead of
        user._generate_jwt_token().
        """
        return self._generate_jwt_token()
    
    # The next methods are hidden 
    # And available to call only inside this class 
    # --------------------------------------------
    # Because they operate with secured data,
    # such as SECRET_KEY

    def _generate_jwt_token(self):
        """
        Generates JWT token which stores the id, 
        activation_time(which is actual for 1 day) of this user
        """
        dt = datetime.datetime.now() + datetime.timedelta(days=1)

        token_payload = {
                'id': str(self.id),
                'exp': dt
                }
        token = str(jwt.encode(token_payload, settings.SECRET_KEY, algorithm='HS256'))
        
        return token[2:len(token) - 1] #There we slicing token to be without prefix