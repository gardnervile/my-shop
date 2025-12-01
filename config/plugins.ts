module.exports = {
  email: {
    config: {
      provider: 'nodemailer',
      providerOptions: {
        host: '127.0.0.1',
        port: 1025,
        secure: false,
      },
      settings: {
        defaultFrom: 'no-reply@localhost',
        defaultReplyTo: 'no-reply@localhost',
      },
    },
  },
};