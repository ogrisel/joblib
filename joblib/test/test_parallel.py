"""
Test the parallel module.
"""

# Author: Gael Varoquaux <gael dot varoquaux at normalesup dot org>
# Copyright (c) 2010-2011 Gael Varoquaux
# License: BSD Style, 3 clauses.

import time
import sys
import shutil
import tempfile
import os
try:
    import cPickle as pickle
    PickleError = TypeError
except:
    import pickle
    PickleError = pickle.PicklingError
try:
    from io import BytesIO
except:
    from cStringIO import StringIO as BytesIO

if sys.version_info[0] == 3:
    PickleError = pickle.PicklingError

from .common import np, with_numpy
from ..parallel import Parallel, delayed, SafeFunction, WorkerInterrupt, \
        multiprocessing, cpu_count
from ..my_exceptions import JoblibException

import nose


TEST_FOLDER = None


def setup_test_folder():
    global TEST_FOLDER
    TEST_FOLDER = tempfile.mkdtemp('joblib-test-parallel-')


def teardown_test_folder():
    if TEST_FOLDER is not None and os.path.exists(TEST_FOLDER):
        shutil.rmtree(TEST_FOLDER)

###############################################################################

def division(x, y):
    return x / y


def square(x):
    return x ** 2


def exception_raiser(x):
    if x == 7:
        raise ValueError
    return x


def interrupt_raiser(x):
    time.sleep(.05)
    raise KeyboardInterrupt


def f(x, y=0, z=0):
    """ A module-level function so that it can be spawn with
    multiprocessing.
    """
    return x ** 2 + y + z


###############################################################################
def test_cpu_count():
    assert cpu_count() > 0


###############################################################################
# Test parallel
def test_simple_parallel():
    X = range(5)
    for n_jobs in (1, 2, -1, -2):
        yield (nose.tools.assert_equal, [square(x) for x in X],
                Parallel(n_jobs=-1)(
                        delayed(square)(x) for x in X))
    try:
        # To smoke-test verbosity, we capture stdout
        orig_stdout = sys.stdout
        sys.stdout = BytesIO()
        orig_stderr = sys.stdout
        sys.stderr = BytesIO()
        for verbose in (2, 11, 100):
                Parallel(n_jobs=-1, verbose=verbose)(
                        delayed(square)(x) for x in X)
                Parallel(n_jobs=1, verbose=verbose)(
                        delayed(square)(x) for x in X)
                Parallel(n_jobs=2, verbose=verbose, pre_dispatch=2)(
                        delayed(square)(x) for x in X)
    except Exception:
        # Cannot use 'except as' to maintain Python 2.5 compatibility
        e = sys.exc_info()[1]
        print sys.stdout.getvalue()
        print sys.stderr.getvalue()
        raise e
    finally:
        sys.stdout = orig_stdout
        sys.stderr = orig_stderr


def nested_loop():
    Parallel(n_jobs=2)(delayed(square)(.01) for _ in range(2))


def test_nested_loop():
    Parallel(n_jobs=2)(delayed(nested_loop)() for _ in range(2))


def test_parallel_kwargs():
    """ Check the keyword argument processing of pmap.
    """
    lst = range(10)
    for n_jobs in (1, 4):
        yield (nose.tools.assert_equal,
               [f(x, y=1) for x in lst],
               Parallel(n_jobs=n_jobs)(delayed(f)(x, y=1) for x in lst)
              )


def test_parallel_pickling():
    """ Check that pmap captures the errors when it is passed an object
        that cannot be pickled.
    """
    def g(x):
        return x ** 2
    nose.tools.assert_raises(PickleError,
                             Parallel(),
                             (delayed(g)(x) for x in range(10))
                            )


def test_error_capture():
    """ Check that error are captured, and that correct exceptions
        are raised.
    """
    if multiprocessing is not None:
        # A JoblibException will be raised only if there is indeed
        # multiprocessing
        nose.tools.assert_raises(JoblibException,
                                Parallel(n_jobs=2),
                    [delayed(division)(x, y) for x, y in zip((0, 1), (1, 0))],
                        )
        nose.tools.assert_raises(WorkerInterrupt,
                                    Parallel(n_jobs=2),
                        [delayed(interrupt_raiser)(x) for x in (1, 0)],
                            )
    else:
        nose.tools.assert_raises(KeyboardInterrupt,
                                    Parallel(n_jobs=2),
                        [delayed(interrupt_raiser)(x) for x in (1, 0)],
                            )
    nose.tools.assert_raises(ZeroDivisionError,
                                Parallel(n_jobs=2),
                    [delayed(division)(x, y) for x, y in zip((0, 1), (1, 0))],
                        )
    try:
        ex = JoblibException
        Parallel(n_jobs=1)(
                    delayed(division)(x, y) for x, y in zip((0, 1), (1, 0)))
    except Exception:
        # Cannot use 'except as' to maintain Python 2.5 compatibility
        ex = sys.exc_info()[1]
    nose.tools.assert_false(isinstance(ex, JoblibException))


class Counter(object):
    def __init__(self, list1, list2):
        self.list1 = list1
        self.list2 = list2

    def __call__(self, i):
        self.list1.append(i)
        nose.tools.assert_equal(len(self.list1), len(self.list2))


def consumer(queue, item):
    queue.append('Consumed %s' % item)


def test_dispatch_one_job():
    """ Test that with only one job, Parallel does act as a iterator.
    """
    queue = list()

    def producer():
        for i in range(6):
            queue.append('Produced %i' % i)
            yield i

    Parallel(n_jobs=1)(delayed(consumer)(queue, x) for x in producer())
    nose.tools.assert_equal(queue,
                              ['Produced 0', 'Consumed 0',
                               'Produced 1', 'Consumed 1',
                               'Produced 2', 'Consumed 2',
                               'Produced 3', 'Consumed 3',
                               'Produced 4', 'Consumed 4',
                               'Produced 5', 'Consumed 5']
                               )
    nose.tools.assert_equal(len(queue), 12)


def test_dispatch_multiprocessing():
    """ Check that using pre_dispatch Parallel does indeed dispatch items
        lazily.
    """
    if multiprocessing is None:
        return
    manager = multiprocessing.Manager()
    queue = manager.list()

    def producer():
        for i in range(6):
            queue.append('Produced %i' % i)
            yield i

    Parallel(n_jobs=2, pre_dispatch=3)(delayed(consumer)(queue, i)
                                       for i in producer())
    nose.tools.assert_equal(list(queue)[:4],
            ['Produced 0', 'Produced 1', 'Produced 2',
             'Consumed 0', ])
    nose.tools.assert_equal(len(queue), 12)


def test_exception_dispatch():
    "Make sure that exception raised during dispatch are indeed captured"
    nose.tools.assert_raises(
            ValueError,
            Parallel(n_jobs=6, pre_dispatch=16, verbose=0),
                    (delayed(exception_raiser)(i) for i in range(30)),
            )


###############################################################################
# Test helpers
def test_joblib_exception():
    # Smoke-test the custom exception
    e = JoblibException('foobar')
    # Test the repr
    repr(e)
    # Test the pickle
    pickle.dumps(e)


def test_safe_function():
    safe_division = SafeFunction(division)
    nose.tools.assert_raises(JoblibException, safe_division, 1, 0)


###############################################################################
# Test special support for unpicklable numpy.memmap arrays

def check_mmap_array(a, basename, dtype, shape, mode, offset, order, data):
    """Check that a is a memmap instance with expected attributes"""
    nose.tools.assert_true(isinstance(a, np.memmap))
    nose.tools.assert_equal(os.path.basename(a.filename), basename)
    nose.tools.assert_equal(a.dtype, dtype)
    nose.tools.assert_equal(a.shape, shape)
    nose.tools.assert_equal(a.mode, mode)
    nose.tools.assert_equal(a.offset, offset)
    actual_order = 'F' if a.flags['F_CONTIGUOUS'] else 'C'
    nose.tools.assert_equal(actual_order, order)
    np.testing.assert_array_equal(a, data)


def check_mmap_in_args(a, b, c, d=None, e=None):
    """Function to be called in parallel in a multiprocessing setup"""
    a_data = np.arange(100).reshape((10, 10)).astype(np.float32).T
    b_data = np.arange(100).reshape((10, 10)).astype(np.int64)[1:, :] * 2

    # Check serialization of a variations
    a_features = ['buffer_1.mmap', np.float32, (10, 10), 'r+', 0, 'F', a_data]
    check_mmap_array(a, *a_features)
    check_mmap_array(c.a, *a_features)
    check_mmap_array(d, *a_features)

    # Check serialization of b variations
    b_features = ['buffer_2.mmap', np.int64, (9, 10), 'c', 80, 'C', b_data]
    check_mmap_array(b, *b_features)
    check_mmap_array(c.b, *b_features)
    check_mmap_array(e, *b_features)

    # Regular numpy arrays are not memmaped
    nose.tools.assert_false(isinstance(c.c, np.memmap))
    np.testing.assert_array_equal(c.c, np.arange(10))

    # Even if the original args are references to one another,
    # the unwrapped variables are not
    #nose.tools.assert_false(a is c.a)
    #nose.tools.assert_false(a is d)
    #nose.tools.assert_false(b is c.b)
    #nose.tools.assert_false(b is e)
    return 'ok'


class SomeClass(object):
    """Dummy class with some attributes"""

    def __init__(self, a, b, c):
        self.a = a
        self.b = b
        self.c = c


@with_numpy
@nose.with_setup(setup_test_folder, teardown_test_folder)
def test_mmap_in_parallel_args():
    # build a simple 2D memory mapped array
    buffer_1 = os.path.join(TEST_FOLDER, 'buffer_1.mmap')
    a = np.memmap(buffer_1, np.float32, shape=(100,), mode='w+')
    a[:] = np.arange(100).astype(a.dtype)
    a = np.memmap(buffer_1, np.float32, shape=(10, 10), mode='r+', order='F')

    # build a memory mapped 2D array with offsetted values
    buffer_2 = os.path.join(TEST_FOLDER, 'buffer_2.mmap')
    b = np.memmap(buffer_2, np.int64, shape=(100,), mode='w+')
    b[:] = (np.arange(100) * 2).astype(b.dtype)
    b = np.memmap(buffer_2, np.int64, mode='c', shape=(9, 10),
                  offset=10 * 64 / 8, order='C')

    # build an object that has memory mapped arrays as direct
    # attributes
    c = SomeClass(a, b, np.arange(10))

    args = [a, b, c]
    kwargs = {'d': a, 'e': b}

    # Check that memory mapped arrays are correctly handled when processed in
    # a multiprocessing env
    n_items = 5
    data_sequence = [(args, kwargs)] * n_items

    results = Parallel(n_jobs=2)(
        delayed(check_mmap_in_args)(*args, **kwargs)
        for args, kwargs in data_sequence)
    nose.tools.assert_equals(results, ['ok'] * n_items)
