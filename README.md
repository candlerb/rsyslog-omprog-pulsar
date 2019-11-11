# rsyslog to pulsar adapter

This is an experimental plugin to be run under rsyslog's
[omprog](https://www.rsyslog.com/doc/v8-stable/configuration/modules/omprog.html)
module.

It publishes log messages to a [pulsar](https://pulsar.apache.org/) topic,
via an rsyslog template to format lines with a JSON metadata prefix:

```
{"metakey":"metavalue",...}Message goes here
```

The metadata is stored as pulsar message properties (headers), and the
message itself as the message body.

## Why separate message and metadata?

A number of common logging systems bundle together the message and metadata
into a single JSON object.

Whilst this is convenient, it has a problem: JSON strings do not carry
arbitrary binary data, only valid Unicode text.  Syslog sources can and
sometimes do generate data which is not valid UTF-8.  You therefore have the
choice of:

1. Your logging system blowing up when an unexpected binary symbol appears;
2. Your logging solution generating something that looks like JSON, but
   technically isn't (and therefore may blow up further down the line);
3. Your logging system "fixing" the message by dropping or replacing invalid
   characters, so you no longer have a record of exactly what was sent.

With pulsar you can avoid this problem: the message body can be retained
exactly as-is.  Certainly you may have to modify it down the line to work
with other systems, but you have control and visibility of the process, and
you have the original message to refer to should you need it.

rsyslog is not completely binary-clean - for example it has to replace
newline with `#012` to work with the line-based omprog protocol - but at
least it avoids character encoding issues.

## Sample configuration: rsyslog

Add to `/etc/rsyslog.conf`:

```
module(load="omprog")
```

Create `/etc/rsyslog.d/10-pulsar.conf`:

```
template(name="pulsar" type="list") {
  constant(value="{\"job\":\"rsyslog\",")
  property(name="timereported" outname="logtime" dateformat="rfc3339" date.inUTC="on" format="jsonf")
  constant(value=",")
  property(name="fromhost-ip" outname="logsrc" format="jsonf" )
  constant(value=",")
  property(name="hostname" format="jsonf")
  constant(value=",")
  property(name="syslogfacility-text" outname="facility" format="jsonf")
  constant(value=",")
  property(name="syslogseverity-text" outname="severity" format="jsonf")
  constant(value="}")
  # Already escaped if EscapecontrolCharactersOnReceive is on (default)
  property(name="syslogtag" controlcharacters="escape")
  property(name="msg" controlcharacters="escape")
  constant(value="\n")
}

*.*  action(type="omprog"
  template="pulsar"
  binary="/home/ubuntu/omprog-wrapper.sh"
  action.resumeInterval="5"
  confirmMessages="on"
  output="/tmp/pulsar.err"
  useTransactions="on"
  #queue.type="LinkedList"
  #queue.minDequeueBatchSize="50"   # only in 8.1901.0+
  #reportFailures="on"              # only in 8.38.0+
  forceSingleInstance="on")
```

For more information, see rsyslog documentation for:

* [Templates](https://www.rsyslog.com/doc/v8-stable/configuration/templates.html)
* [Properties](https://www.rsyslog.com/doc/master/configuration/properties.html)
* [Property replacer](https://www.rsyslog.com/doc/master/configuration/property_replacer.html)

## Sample configuration: omprog-pulsar.py

See the provided [omprog-pulsar.yaml](omprog-pulsar.yaml) file.

## Reading logs

A small utility "tail-pulsar" is included which can be used to read the logs out
of a pulsar topic.

## Tuning

When using `confirmMessages="on"` for reliable delivery, you should also set
`useTransactions="on"` for best throughput.

Under low load, rsyslog will prefer to minimise latency by sending batches
of size 1.  As load increases, the batch size should also increase.
omprog-pulsar.py waits for pulsar to confirm delivery of the last message in
each batch, before confirming success back to rsyslog.

Adding a delay can put more messages into a batch, which might reduce the
system load slightly.  This requires rsyslog v8.1901.0 or later with the
[queue.minDequeueBatchSize](https://www.rsyslog.com/doc/master/rainerscript/queue_parameters.html#queue-mindequeuebatchsize)
[feature](https://github.com/rsyslog/rsyslog/issues/495).

You can also configure batching in the pulsar client:

```
producer:
  batching_enabled: True
  batching_max_publish_delay_ms: 100
```

This will cause the acks back to rsyslog to be delayed, which will force
rsyslog to buffer more messages.

In practice, the benefits of either approach are likely to be minimal.

## Caveats

Errors in your template can send `**INVALID PROPERTY NAME**` without a
newline, and the external prog will hang waiting for one.

If `confirmMessages` is not enabled, messages may be lost when you restart
rsyslog or omprog-pulsar.py.

If you enable `confirmMessages` in rsyslog then you must also enable it in
`omprog-pulsar.yaml`, otherwise rsyslog will hang.

To use pulsar for long-term retention of logs, and to allow subscribers to
replay older logs, you should create a new namespace for your logs and
set a suitable
[message retention policy](https://pulsar.apache.org/docs/en/cookbooks-retention-expiry/).

## Licence

This work is released under GPLv3 (same as rsyslog itself)
