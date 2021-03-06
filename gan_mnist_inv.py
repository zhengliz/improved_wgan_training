import os
import sys
import time

import matplotlib
import numpy as np
import tensorflow as tf

import tflib as lib
import tflib.mnist
import tflib.ops.batchnorm
import tflib.ops.conv2d
import tflib.ops.deconv2d
import tflib.ops.linear
import tflib.plot
import tflib.save_images

from parzen import *

sys.path.append(os.getcwd())
matplotlib.use('Agg')

MODE = 'wgan-gp'
DIM = 64
BATCH_SIZE = 50
CRITIC_ITERS = 5
LAMBDA = 10
ITERS = 200000
OUTPUT_DIM = 28 * 28
NOISE_DIM = 128
ROWS = 10
STD = 1.0
OUTPUT_PATH = os.getcwd().replace("Repositories", "Output")

lib.print_model_settings(locals().copy())


def LeakyReLU(x, beta=0.2):
  return tf.maximum(beta * x, x)


def ReLULayer(name, n_in, n_out, inputs):
  output = lib.ops.linear.Linear(name + '.Linear', n_in, n_out, inputs,
                                 initialization='he')
  return tf.nn.relu(output)


def LeakyReLULayer(name, n_in, n_out, inputs):
  output = lib.ops.linear.Linear(name + '.Linear', n_in, n_out, inputs,
                                 initialization='he')
  return LeakyReLU(output)


def Generator(n_samples, noise=None):
  if noise is None:
    noise = tf.random_normal([n_samples, NOISE_DIM])

  output = lib.ops.linear.Linear('Generator.Input', NOISE_DIM, 4 * DIM * 4 * 4,
                                 noise)
  if MODE == 'wgan':
    output = lib.ops.batchnorm.Batchnorm('Generator.BN1', [0], output)
  output = tf.nn.relu(output)
  output = tf.reshape(output, [-1, 4 * DIM, 4, 4])  # 4 x 4

  output = lib.ops.deconv2d.Deconv2D('Generator.2', 4 * DIM, 2 * DIM, 5, output)
  if MODE == 'wgan':
    output = lib.ops.batchnorm.Batchnorm('Generator.BN2', [0, 2, 3], output)
  output = tf.nn.relu(output)  # 8 x 8
  output = output[:, :, :7, :7]  # 7 x 7

  output = lib.ops.deconv2d.Deconv2D('Generator.3', 2 * DIM, DIM, 5, output)
  if MODE == 'wgan':
    output = lib.ops.batchnorm.Batchnorm('Generator.BN3', [0, 2, 3], output)
  output = tf.nn.relu(output)  # 14 x 14

  output = lib.ops.deconv2d.Deconv2D('Generator.Output', DIM, 1, 5, output)
  output = tf.nn.sigmoid(output)  # 28 x 28

  return tf.reshape(output, [-1, OUTPUT_DIM])


def Discriminator(inputs):
  output = tf.reshape(inputs, [-1, 1, 28, 28])  # 28 x 28

  output = lib.ops.conv2d.Conv2D('Discriminator.Input', 1, DIM, 5, output,
                                 stride=2)
  output = LeakyReLU(output)  # 14 x 14

  output = lib.ops.conv2d.Conv2D('Discriminator.2', DIM, 2 * DIM, 5, output,
                                 stride=2)
  if MODE == 'wgan':
    output = lib.ops.batchnorm.Batchnorm('Discriminator.BN2', [0, 2, 3], output)
  output = LeakyReLU(output)  # 7 x 7

  output = lib.ops.conv2d.Conv2D('Discriminator.3', 2 * DIM, 4 * DIM, 5, output,
                                 stride=2)
  if MODE == 'wgan':
    output = lib.ops.batchnorm.Batchnorm('Discriminator.BN3', [0, 2, 3], output)
  output = LeakyReLU(output)  # 4 x 4

  output = tf.reshape(output, [-1, 4 * DIM * 4 * 4])

  discriminator_output = lib.ops.linear.Linear('Discriminator.Output',
                                               4 * DIM * 4 * 4, 1, output)
  discriminator_output = tf.reshape(discriminator_output, [-1])

  invertor_output = lib.ops.linear.Linear('Invertor.4', 4 * DIM * 4 * 4,
                                          4 * DIM * 4, output)
  invertor_output = LeakyReLU(invertor_output)
  invertor_output = tf.nn.dropout(invertor_output, keep_prob=0.5)

  invertor_output = lib.ops.linear.Linear('Invertor.Output', 4 * DIM * 4,
                                          NOISE_DIM, invertor_output)

  # invertor_output = lib.ops.linear.Linear('Invertor.Output', 4 * DIM * 4 * 4,
  #                                         NOISE_DIM, output)
  invertor_output = tf.reshape(invertor_output, [-1, NOISE_DIM])

  return discriminator_output, invertor_output


# Build graph
real_data = tf.placeholder(tf.float32, shape=[BATCH_SIZE, OUTPUT_DIM])
input_noise = tf.placeholder(tf.float32, shape=[BATCH_SIZE, NOISE_DIM])
fake_data = Generator(BATCH_SIZE, input_noise)

dis_real, _ = Discriminator(real_data)
dis_fake, invert_noise = Discriminator(fake_data)

gen_params = lib.params_with_name('Generator')
dis_params = lib.params_with_name('Discriminator')
inv_params = lib.params_with_name('Invertor')

# Optimize cost function
if MODE == 'wgan':
  inv_cost = tf.reduce_mean(tf.square(input_noise - invert_noise))
  gen_cost = -tf.reduce_mean(dis_fake)
  dis_cost = tf.reduce_mean(dis_fake) - tf.reduce_mean(dis_real)

  inv_train_op = tf.train.RMSPropOptimizer(learning_rate=5e-5).minimize(
    inv_cost, var_list=inv_params)
  gen_train_op = tf.train.RMSPropOptimizer(learning_rate=5e-5).minimize(
    gen_cost, var_list=gen_params)
  dis_train_op = tf.train.RMSPropOptimizer(learning_rate=5e-5).minimize(
    dis_cost, var_list=dis_params)

  clip_ops = []
  clip_bounds = [-.01, .01]
  for var in dis_params:
    clip_ops.append(
      tf.assign(var, tf.clip_by_value(var, clip_bounds[0], clip_bounds[1])))
  clip_dis_weights = tf.group(*clip_ops)

elif MODE == 'wgan-gp':
  inv_cost = tf.reduce_mean(tf.square(input_noise - invert_noise))
  gen_cost = -tf.reduce_mean(dis_fake)
  dis_cost = tf.reduce_mean(dis_fake) - tf.reduce_mean(dis_real)

  alpha = tf.random_uniform(shape=[BATCH_SIZE, 1], minval=0., maxval=1.)
  differences = fake_data - real_data
  interpolates = real_data + alpha * differences
  gradients = tf.gradients(Discriminator(interpolates)[0], [interpolates])[0]
  slopes = tf.sqrt(tf.reduce_sum(tf.square(gradients), axis=1))
  gradient_penalty = tf.reduce_mean((slopes - 1.) ** 2)
  dis_cost_gp = dis_cost + LAMBDA * gradient_penalty

  inv_train_op = tf.train.AdamOptimizer(learning_rate=1e-4, beta1=0.5,
                                        beta2=0.9).minimize(inv_cost,
                                                            var_list=inv_params)
  gen_train_op = tf.train.AdamOptimizer(learning_rate=1e-4, beta1=0.5,
                                        beta2=0.9).minimize(gen_cost,
                                                            var_list=gen_params)
  dis_train_op = tf.train.AdamOptimizer(learning_rate=1e-4, beta1=0.5,
                                        beta2=0.9).minimize(dis_cost_gp,
                                                            var_list=dis_params)
  clip_dis_weights = None

elif MODE == 'dcgan':
  inv_cost = tf.reduce_mean(tf.square(input_noise - invert_noise))
  gen_cost = tf.reduce_mean(
    tf.nn.sigmoid_cross_entropy_with_logits(logits=dis_fake,
                                            labels=tf.ones_like(dis_fake)))
  dis_cost = tf.reduce_mean(
    tf.nn.sigmoid_cross_entropy_with_logits(logits=dis_fake,
                                            labels=tf.zeros_like(dis_fake)))
  dis_cost += tf.reduce_mean(
    tf.nn.sigmoid_cross_entropy_with_logits(logits=dis_real,
                                            labels=tf.ones_like(dis_real)))
  dis_cost /= 2.

  inv_train_op = tf.train.AdamOptimizer(learning_rate=2e-4, beta1=0.5).minimize(
    inv_cost, var_list=inv_params)
  gen_train_op = tf.train.AdamOptimizer(learning_rate=2e-4, beta1=0.5).minimize(
    gen_cost, var_list=gen_params)
  dis_train_op = tf.train.AdamOptimizer(learning_rate=2e-4, beta1=0.5).minimize(
    dis_cost, var_list=dis_params)
  clip_dis_weights = None

# For saving samples
fixed_noise = tf.constant(
  np.random.normal(size=(128, NOISE_DIM)).astype('float32'))
fixed_noise_samples = Generator(128, noise=fixed_noise)


def generate_image(session, fixed_noise_samples, frame):
  samples = session.run(fixed_noise_samples)
  lib.save_images.save_images(
    samples.reshape((128, 28, 28)),
    os.path.join(OUTPUT_PATH, 'samples/mnist/sample_{}.png'.format(frame)))


# Dataset iterator
train_gen, dev_gen, test_gen = lib.mnist.load(BATCH_SIZE, BATCH_SIZE)


def inf_train_gen():
  while True:
    for images, targets in train_gen():  # targets are labels in range(10)
      yield images


# For sampling around real images
for images, targets in train_gen():
  targets = targets.tolist()
  indices = []
  for label in range(10):
    try:
      indices.append(targets.index(label))
    except ValueError:
      break
  if len(indices) == ROWS:
    fixed_real_samples = images[indices]
    break


def sample_image(session, fixed_real_samples, frame):
  _, noise_mus = Discriminator(fixed_real_samples)
  mus = session.run(noise_mus)
  extended_noise = []
  delta_noise = np.random.multivariate_normal(mean=np.zeros_like(mus[0]),
                                              cov=STD * np.identity(NOISE_DIM),
                                              size=ROWS - 2)
  for k in xrange(ROWS):
    extended_noise.append(mus[k])
    extended_noise.extend(delta_noise + mus[k])
  sampled_noise = tf.cast(tf.constant(np.asarray(extended_noise)), 'float32')
  sampled_noise_images = Generator(ROWS * (ROWS - 1), noise=sampled_noise)
  generated_noise_images = session.run(sampled_noise_images)
  samples = []
  for k in xrange(ROWS):
    samples.append(fixed_real_samples[k])
    samples.extend(generated_noise_images[k * (ROWS - 1):(k + 1) * (ROWS - 1)])
  lib.save_images.save_images(
    np.reshape(samples, (ROWS * ROWS, 28, 28)), os.path.join(
      OUTPUT_PATH, 'samples/mnist/perturbation_{}.png'.format(frame)))


if __name__ == '__main__':
  saver = tf.train.Saver(max_to_keep=1000)

  # load data, dev and test
  _, dev_data, test_data = lib.mnist.load_data()

  # Train loop
  with tf.Session() as session:
    session.run(tf.global_variables_initializer())
    gen = inf_train_gen()
    if MODE == 'dcgan':
      dis_iters = 1
    else:
      dis_iters = CRITIC_ITERS

    for iteration in xrange(ITERS):
      start_time = time.time()
      _input_noise = np.random.normal(size=(BATCH_SIZE, NOISE_DIM))

      _dis_cost = []
      for i in xrange(dis_iters):
        _data = gen.next()
        _dis_cost_, _ = session.run([dis_cost, dis_train_op],
                                    feed_dict={real_data: _data,
                                               input_noise: _input_noise})
        _dis_cost.append(_dis_cost_)
        if clip_dis_weights:
          _ = session.run(clip_dis_weights)
      _dis_cost = np.mean(_dis_cost)

      _ = session.run(gen_train_op, feed_dict={input_noise: _input_noise})
      _inv_cost, _ = session.run([inv_cost, inv_train_op],
                                 feed_dict={input_noise: _input_noise})

      lib.plot.plot('train discriminator cost', _dis_cost)
      lib.plot.plot('train invertor cost', _inv_cost)
      lib.plot.plot('time', time.time() - start_time)

      # Calculate dev loss and generate samples every 1000 iters
      if iteration % 1000 == 999:
        dev_dis_costs = []
        for images, _ in dev_gen():
          _dev_dis_cost = session.run(dis_cost,
                                      feed_dict={real_data: images,
                                                 input_noise: _input_noise})
          dev_dis_costs.append(_dev_dis_cost)
        lib.plot.plot('dev discriminator cost', np.mean(dev_dis_costs))

        # generate_image(session, fixed_noise_samples, iteration)
        sample_image(session, fixed_real_samples, iteration)

      # Save checkpoints and evaluate model every 10000 iters
      if iteration % 10000 == 9999:
        save_path = saver.save(session, os.path.join(
          OUTPUT_PATH, "models/mnist/model"), global_step=iteration)
        print("Model saved in file: %s" % save_path)

        # generate samples
        gen_samples = Generator(NUM_SAMPLES).eval()

        # cross validate sigma
        # sigma_range = np.logspace(-.9, -.5, 5)
        # sigma = cross_validate_sigma(gen_samples, dev_data[0], sigma_range,
        #                              BATCH_SIZE)
        # print "Using Sigma: {}".format(sigma)
        # lib.plot.plot('sigma', sigma)

        sigma = 0.2

        # fit and evaulate
        parzen = theano_parzen(gen_samples, sigma)
        ll_mean, ll_std = get_nll(test_data[0], parzen, BATCH_SIZE)
        ll_std /= np.sqrt(test_data[0].shape[0])
        print "Log-Likelihood of test set = {}, se: {}".format(ll_mean, ll_std)
        lib.plot.plot('test log likelihood', ll_mean)

      # Write logs every 100 iters
      if iteration < 5 or iteration % 100 == 99:
        lib.plot.flush()

      lib.plot.tick()
