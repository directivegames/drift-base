from flask_marshmallow.fields import AbsoluteURLFor
from marshmallow import pre_dump, fields, Schema
from marshmallow_sqlalchemy import SQLAlchemyAutoSchema
from driftbase.models.db import CorePlayer
from flask import url_for

class PlayerSchema(SQLAlchemyAutoSchema):
    class Meta:
        strict = True
        include_fk = True # required to expose the 'user_id' field
        model = CorePlayer
        exclude = ('player_summary', 'user', 'clients')
        load_instance = True
        include_relationships = True

    is_online = fields.Boolean()

    player_url = AbsoluteURLFor(
        'players.entry',
        values=dict(player_id='<player_id>'),
    )

    gamestates_url = AbsoluteURLFor(
        'player_gamestate.list',
        values=dict(player_id='<player_id>'),
    )
    journal_url = AbsoluteURLFor(
        'player_journal.list',
        values=dict(player_id='<player_id>'),
    )
    user_url = AbsoluteURLFor(
        'users.entry',
        values=dict(user_id='<user_id>'),
    )
    messagequeue_url = fields.Str(
        description="Fully qualified URL of the players' message queue resource"
    )
    messagequeue2_url = fields.Str(
        description="Fully qualified URL of the players' message queue resource"
    )
    messages_url = AbsoluteURLFor(
        'messages.exchange',
        values=dict(
            exchange='players',
            exchange_id='<player_id>',
        )
    )
    summary_url = AbsoluteURLFor(
        'player_summary.list',
        values=dict(player_id='<player_id>',)
    )
    richpresence_url = AbsoluteURLFor(
        'richpresence.entry',
        values=dict(player_id='<player_id>'),
    )
    countertotals_url = AbsoluteURLFor(
        'player_counters.totals',
        values=dict(player_id='<player_id>'),
    )
    counter_url = AbsoluteURLFor(
        'player_counters.list',
        values=dict(player_id='<player_id>'),
    )
    tickets_url = AbsoluteURLFor(
        'player_tickets.list',
        values=dict(player_id='<player_id>'),
    )

    @pre_dump
    def populate_urls(self, obj, many=False):
        obj.messagequeue_url = (
            url_for(
                'messages.exchange',
                exchange='players',
                exchange_id=obj.player_id,
                _external=True,
            )
            + '/{queue}'
        )
        return obj
