#!/usr/bin/env python3

# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import json
import pulsar
import sys
import time

try:
    # Only for parse_timestamp=True.  Minimum version 2.7
    import dateutil.parser
except LoadError:
    pass

class OmprogPulsar:
    def __init__(self, producer,
                 stdin=sys.stdin, stdout=sys.stdout, stderr=sys.stderr,
                 confirm_messages=False,
                 parse_timestamp=False,
                 begin_transaction_mark=b"BEGIN TRANSACTION\n",
                 commit_transaction_mark=b"COMMIT TRANSACTION\n"):
        """
        Object which communicates with rsyslog omprog on stdin/stdout
        and forwards messages using a Pulsar producer
        """
        self.producer = producer
        self.stdin = stdin
        self.stdout = stdout
        self.stderr = stderr
        self.confirm_messages = confirm_messages
        self.parse_timestamp = parse_timestamp
        self.begin_transaction_mark = begin_transaction_mark
        self.commit_transaction_mark = commit_transaction_mark

    def forward(self, events):
        results = []
        sent = 0
        for msg, meta, ts in events:
            self.producer.send_async(msg, properties=meta, event_timestamp=ts,
                                     callback=lambda r, m: results.append(r))
            sent += 1
        if not sent:
            return "OK"
        events.clear()
        if not self.confirm_messages:
            return "OK"
        self.producer.flush()
        # https://github.com/apache/pulsar/issues/5666
        if len(results) != sent:
            for i in range(100):
                time.sleep(0.1)
                if len(results) == sent:
                    break
            else:
                return "Pulsar send_async: got %d results, expecting %d" % (len(results), count)
        # Find the first error result, otherwise return "OK"
        return next(("Pulsar error: "+str(e) for e in results if e != pulsar.Result.Ok), "OK")

    def run(self):
        def confirm(status):
            """Send response to rsyslog"""
            if self.confirm_messages:
                print(status, file=self.stdout, flush=True)

        print("Starting...", file=self.stderr)
        confirm("OK") # signal we are ready

        in_transaction = False
        events = []
        while True:
            # Use binary mode so we cannot be fazed by non-UTF8 data
            line = self.stdin.buffer.readline()
            if not line:
                break
            #print(repr(line), file=self.stderr)
            if line == self.begin_transaction_mark:
                in_transaction = True
                confirm("OK")
                continue
            if line == self.commit_transaction_mark:
                in_transaction = False
                res = self.forward(events)
                confirm(res)
                continue
            try:
                pj = line.index(b'"}')
                meta = json.loads(line[0:pj+2].decode("UTF-8", errors="replace"))
                msg = line[pj+2:-1]       # strip trailing \n
                if msg and msg[0] == 32:  # strip leading space
                    msg = msg[1:]
                ts = None
                if self.parse_timestamp:
                    try:
                        ts = int(dateutil.parser.isoparse(meta["logtime"]).timestamp()*1000.0)
                        del meta["logtime"]
                    except Exception:
                        pass # ignore timestamp parsing errors
                events.append((msg, meta, ts))
            except Exception as e:
                # This line is badly formatted: we don't want to receive it again
                print("Invalid line: %r: %s" % (line, e), file=self.stderr)
            if in_transaction:
                confirm("DEFER_COMMIT")
                continue
            # If transaction mode not in use, flush and acknowledge
            res = self.forward(events)
            confirm(res)

if __name__ == "__main__":
    import argparse
    import os
    import yaml

    parser = argparse.ArgumentParser()
    parser.add_argument("--config", "-c", default="omprog-pulsar.yaml", help="YAML configuration file")
    args = parser.parse_args()
    with open(args.config) as f:
        config = yaml.load(f)
        if not isinstance(config, dict):
            raise RuntimeError("config must be a dict, not %s" % type(config))

    # Workaround for https://github.com/apache/pulsar/issues/5620
    fd = os.dup(1)    # copy the original stdout
    os.dup2(2, 1)     # join stdout onto stderr
    new_stdout = os.fdopen(fd, "w")  # wrap the original stdout

    client = pulsar.Client(**config["client"])
    producer = client.create_producer(**config["producer"])
    try:
        omprog = OmprogPulsar(producer=producer, stdout=new_stdout, **config.get("omprog", {}))
        omprog.run()
    finally:
        producer.close()
        client.close()
