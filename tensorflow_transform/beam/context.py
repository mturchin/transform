# Copyright 2019 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Context manager for tensorflow-transform."""

from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import collections
import os
import threading

# GOOGLE-INITIALIZATION

import tensorflow as tf


class Context(object):
  """Context manager for tensorflow-transform.

  All the attributes in this context are kept on a thread local state.

  Attributes:
    temp_dir: (Optional) The temporary directory used within in this block.
    desired_batch_size: (Optional) A batch size to batch elements by. If not
        provided, a batch size will be computed automatically.
    passthrough_keys: (Optional) A set of strings that are keys to
        instances that should pass through the pipeline and be hidden from
        the preprocessing_fn. This should only be used in cases where additional
        information should be attached to instances in the pipeline which should
        not be part of the transformation graph, instance keys is one such
        example.

  Note that the temp dir should be accessible to worker jobs, e.g. if running
  with the Cloud Dataflow runner, the temp dir should be on GCS and should have
  permissions that allow both launcher and workers to access it.
  """

  class _State(
      collections.namedtuple('_State', [
          'temp_dir',
          'desired_batch_size',
          'passthrough_keys',
          'use_deep_copy_optimization',
      ])):
    pass

  class _StateStack(object):
    """Stack of states for this context manager (found in thread-local storage).
    """

    def __init__(self):
      self.frames = []

  # TODO(b/36359436) Ensure tf.Transform code only uses consistent filesystem
  # operations on Cloud.
  _TEMP_SUBDIR = 'tftransform_tmp'

  _thread_local = threading.local()

  def __init__(self,
               temp_dir=None,
               desired_batch_size=None,
               passthrough_keys=None,
               use_deep_copy_optimization=None):
    state = getattr(self._thread_local, 'state', None)
    if not state:
      self._thread_local.state = self._StateStack()
      self._thread_local.state.frames.append(
          self._State(*(None,) * len(self._State._fields)))

    self._temp_dir = temp_dir
    self._desired_batch_size = desired_batch_size
    self._passthrough_keys = passthrough_keys
    self._use_deep_copy_optimization = use_deep_copy_optimization

  def __enter__(self):
    # Previous State's properties are inherited if not explicitly specified.
    last_frame = self._get_topmost_state_frame()
    self._thread_local.state.frames.append(
        self._State(
            temp_dir=self._temp_dir
            if self._temp_dir is not None else last_frame.temp_dir,
            desired_batch_size=self._desired_batch_size
            if self._desired_batch_size is not None else
            last_frame.desired_batch_size,
            passthrough_keys=self._passthrough_keys if
            self._passthrough_keys is not None else last_frame.passthrough_keys,
            use_deep_copy_optimization=self._use_deep_copy_optimization
            if self._use_deep_copy_optimization is not None else
            last_frame.use_deep_copy_optimization,
        ))

  def __exit__(self, *exn_info):
    self._thread_local.state.frames.pop()

  @classmethod
  def _get_topmost_state_frame(cls):
    if hasattr(cls._thread_local, 'state') and cls._thread_local.state.frames:
      return cls._thread_local.state.frames[-1]
    return None

  @classmethod
  def create_base_temp_dir(cls):
    """Generate a temporary location."""
    state = cls._get_topmost_state_frame()
    if state is None or not state.temp_dir:
      raise ValueError(
          'A tf.Transform function that required a temp dir was called but no '
          'temp dir was set.  To set a temp dir use the impl.Context context '
          'manager.')
    base_temp_dir = os.path.join(state.temp_dir, cls._TEMP_SUBDIR)

    # TODO(b/35363519): Perhaps use Beam IO eventually?
    tf.io.gfile.makedirs(base_temp_dir)
    return base_temp_dir

  @classmethod
  def get_desired_batch_size(cls):
    """Retrieves a user set fixed batch size, None if not set."""
    state = cls._get_topmost_state_frame()
    if state is not None and state.desired_batch_size is not None:
      tf.compat.v1.logging.info('Using fixed batch size: %d',
                                state.desired_batch_size)
      return state.desired_batch_size
    return None

  @classmethod
  def get_passthrough_keys(cls):
    """Retrieves a user set passthrough_keys, None if not set."""
    state = cls._get_topmost_state_frame()
    if state is not None and state.passthrough_keys is not None:
      return state.passthrough_keys
    return set()

  @classmethod
  def get_use_deep_copy_optimization(cls):
    """Retrieves a user set use_deep_copy_optimization, None if not set."""
    state = cls._get_topmost_state_frame()
    if state is not None and state.use_deep_copy_optimization is not None:
      return state.use_deep_copy_optimization
    return False
