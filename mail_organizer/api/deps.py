from fastapi import Request

from mail_organizer.accounts import AccountService
from mail_organizer.db import Database


def get_db(request: Request) -> Database:
    return request.app.state.db


def get_account_service(request: Request) -> AccountService:
    return request.app.state.account_service
