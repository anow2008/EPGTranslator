import time

class AutoflushCache:
    def __init__(self, default_timeout, null_return=None):
        self.cache = {}
        self.clear_time = []
        self.dflt_rel_timeout = abs(default_timeout)
        self.null_return = null_return

    def change_timeout(self, new_timeout):
        self.dflt_rel_timeout = abs(new_timeout)

    def flush(self):
        now = time.time()
        clear_to = str(int(now))
        ix = 0
        while ix < len(self.clear_time):
            nx = ix + 1
            if self.clear_time[ix][0] > clear_to:
                break
            ix = nx
        if ix > 0:
            for kx in range(ix):
                del self.cache[self.clear_time[kx][1]]
            del self.clear_time[0:ix]
        return now

    def add(self, key, val, abs_timeout=0):
        now = self.flush()
        if key in self.cache:
            self.clear_time.remove(key)
        self.cache[key] = val
        if abs_timeout > 0:
            until = str(int(abs_timeout))
        else:
            until = str(int(now + self.dflt_rel_timeout))
        ix = 0
        while ix < len(self.clear_time):
            nx = ix + 1
            if self.clear_time[ix][0] > until:
                break
            ix = nx
        self.clear_time.insert(ix, (until, key))

    def fetch(self, key):
        self.flush()
        if key in self.cache:
            retval = self.cache[key]
            return retval
        retval = self.null_return
        return retval

    def delete(self, key):
        if key in self.cache:
            del self.cache[key]
            self.clear_time.remove(key)

    def purge(self):
        self.cache = {}
        self.clear_time = []

    def __del__(self):
        self.purge()


