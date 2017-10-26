
import trio
import pytest

from . import testcase
from . import testing
from .. import exceptions
from ..properties import Properties


class TestConsume(testcase.RabbitTestCase):

    _multiprocess_can_split_ = True


    def setUp(self):
        super().setUp()
        self.consume_future = trio.Event()

    async def callback(self, channel, body, envelope, properties):
        self.consume_future.set_result((body, envelope, properties))

    async def get_callback_result(self):
        await self.consume_future
        result = self.consume_future.result()
        self.consume_future = trio.Event()
        return result


    async def test_wrong_callback_argument(self, amqp):

        def badcallback():
            pass

        await self.channel.queue_declare("q", exclusive=True, no_wait=False)
        await self.channel.exchange_declare("e", "fanout")
        await self.channel.queue_bind("q", "e", routing_key='')

        # get a different channel
        channel = await self.create_channel()

        # publish
        await channel.publish("coucou", "e", routing_key='',)

        # assert there is a message to consume
        await self.check_messages("q",1)

        # start consume
        with pytest.raises(exceptions.ConfigurationError):
            await channel.basic_consume(badcallback, queue_name="q")

    async def test_consume(self, amqp):
        # declare
        await self.channel.queue_declare("q", exclusive=True, no_wait=False)
        await self.channel.exchange_declare("e", "fanout")
        await self.channel.queue_bind("q", "e", routing_key='')

        # get a different channel
        channel = await self.create_channel()

        # publish
        await channel.publish("coucou", "e", routing_key='',)

        # start consume
        await channel.basic_consume(self.callback, queue_name="q")

        # get one
        body, envelope, properties = await self.get_callback_result()
        assert envelope.consumer_tag is not None
        assert envelope.delivery_tag is not None
        assert b"coucou" == body
        assert isinstance(properties, Properties)

    async def test_big_consume(self, amqp):
        # declare
        await self.channel.queue_declare("q", exclusive=True, no_wait=False)
        await self.channel.exchange_declare("e", "fanout")
        await self.channel.queue_bind("q", "e", routing_key='')


        # get a different channel
        channel = await self.create_channel()

        # publish
        await channel.publish("a"*1000000, "e", routing_key='',)

        # start consume
        await channel.basic_consume(self.callback, queue_name="q")

        # get one
        body, envelope, properties = await self.get_callback_result()
        assert envelope.consumer_tag is not None
        assert envelope.delivery_tag is not None
        assert b"a"*1000000 == body
        assert isinstance(properties, Properties)

    async def test_consume_multiple_queues(self, amqp):
        await self.channel.queue_declare("q1", exclusive=True, no_wait=False)
        await self.channel.queue_declare("q2", exclusive=True, no_wait=False)
        await self.channel.exchange_declare("e", "direct")
        await self.channel.queue_bind("q1", "e", routing_key="q1")
        await self.channel.queue_bind("q2", "e", routing_key="q2")

        # get a different channel
        channel = await self.create_channel()

        q1_future = trio.Event()

        async def q1_callback(channel, body, envelope, properties):
            self.q1_result = (body, envelope, properties)
            q1_future.set()

        q2_future = trio.Event()

        async def q2_callback(channel, body, envelope, properties):
            self.q2_result = (body, envelope, properties)
            q2_future.set()

        # start consumers
        result = await channel.basic_consume(q1_callback, queue_name="q1")
        ctag_q1 = result['consumer_tag']
        result = await channel.basic_consume(q2_callback, queue_name="q2")
        ctag_q2 = result['consumer_tag']

        # put message in q1
        await channel.publish("coucou1", "e", "q1")

        # get it
        await q1_future.wait()
        body1, envelope1, properties1 = self.q1_result
        assert ctag_q1 == envelope1.consumer_tag
        assert envelope1.delivery_tag is not None
        assert b"coucou1" == body1
        assert isinstance(properties1, Properties)

        # put message in q2
        await channel.publish("coucou2", "e", "q2")

        # get it
        await q2_future.wait()
        body2, envelope2, properties2 = self.q2_result
        assert ctag_q2 == envelope2.consumer_tag
        assert b"coucou2" == body2
        assert isinstance(properties2, Properties)

    async def test_duplicate_consumer_tag(self, amqp):
        await self.channel.queue_declare("q1", exclusive=True, no_wait=False)
        await self.channel.queue_declare("q2", exclusive=True, no_wait=False)
        await self.channel.basic_consume(self.callback, queue_name="q1", consumer_tag='tag')

        with pytest.raises(exceptions.ChannelClosed) as cm:
            await self.channel.basic_consume(self.callback, queue_name="q2", consumer_tag='tag')

        assert cm.exception.code == 530

    async def test_consume_callaback_synced(self, amqp):
        # declare
        await self.channel.queue_declare("q", exclusive=True, no_wait=False)
        await self.channel.exchange_declare("e", "fanout")
        await self.channel.queue_bind("q", "e", routing_key='')

        # get a different channel
        channel = await self.create_channel()

        # publish
        await channel.publish("coucou", "e", routing_key='',)

        sync_future = trio.Event()

        async def callback(channel, body, envelope, properties):
            assert sync_future.done()

        await channel.basic_consume(callback, queue_name="q")
        sync_future.set()
