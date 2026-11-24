// Written by the server's own coverage.coverage over the starter set's phonetic and prosodic prompts (25 recorded),
// with 12 generated prompts waiting: what GET /api/coverage answers part way through a pilot. Not edited by hand.
import type { Coverage } from '../api'

export const coverageSample: Coverage = {
  prompts: 25,
  waiting: 12,
  phonemised: true,
  groups: [
    {
      key: 'phoneme',
      title: 'Phonemes',
      covered: 43,
      inventory: 43,
      units: [
        {
          value: 'ɜː',
          count: 2,
          example: 'nurse',
        },
        {
          value: 'ɔɪ',
          count: 2,
          example: 'choice',
        },
        {
          value: 'iə',
          count: 3,
          example: 'near',
        },
        {
          value: 'tʃ',
          count: 4,
          example: 'chin',
        },
        {
          value: 'ʒ',
          count: 5,
          example: 'measure',
        },
        {
          value: 'eə',
          count: 5,
          example: 'square',
        },
        {
          value: 'dʒ',
          count: 6,
          example: 'gin',
        },
        {
          value: 'ʃ',
          count: 6,
          example: 'shin',
        },
        {
          value: 'ʊ',
          count: 6,
          example: 'foot',
        },
        {
          value: 'aʊ',
          count: 6,
          example: 'mouth',
        },
        {
          value: 'h',
          count: 8,
          example: 'hat',
        },
        {
          value: 'ɡ',
          count: 9,
          example: 'go',
        },
        {
          value: 'θ',
          count: 10,
          example: 'thin',
        },
        {
          value: 'ɑː',
          count: 10,
          example: 'palm',
        },
        {
          value: 'ɔː',
          count: 10,
          example: 'thought',
        },
        {
          value: 'v',
          count: 12,
          example: 'van',
        },
        {
          value: 'j',
          count: 12,
          example: 'yes',
        },
        {
          value: 'uː',
          count: 13,
          example: 'goose',
        },
        {
          value: 'eɪ',
          count: 13,
          example: 'face',
        },
        {
          value: 'əʊ',
          count: 13,
          example: 'goat',
        },
        {
          value: 'm',
          count: 14,
          example: 'man',
        },
        {
          value: 'ŋ',
          count: 14,
          example: 'sing',
        },
        {
          value: 'iː',
          count: 14,
          example: 'fleece',
        },
        {
          value: 'aɪ',
          count: 14,
          example: 'price',
        },
        {
          value: 'ʌ',
          count: 16,
          example: 'strut',
        },
        {
          value: 'æ',
          count: 18,
          example: 'trap',
        },
        {
          value: 'w',
          count: 19,
          example: 'wet',
        },
        {
          value: 'ɒ',
          count: 20,
          example: 'lot',
        },
        {
          value: 'p',
          count: 21,
          example: 'pin',
        },
        {
          value: 'b',
          count: 21,
          example: 'bin',
        },
        {
          value: 'f',
          count: 21,
          example: 'fin',
        },
        {
          value: 'z',
          count: 23,
          example: 'zoo',
        },
        {
          value: 'ɛ',
          count: 24,
          example: 'dress',
        },
        {
          value: 'l',
          count: 31,
          example: 'let',
        },
        {
          value: 'ɹ',
          count: 34,
          example: 'red',
        },
        {
          value: 'k',
          count: 35,
          example: 'kin',
        },
        {
          value: 'd',
          count: 36,
          example: 'din',
        },
        {
          value: 's',
          count: 36,
          example: 'sin',
        },
        {
          value: 'ð',
          count: 41,
          example: 'then',
        },
        {
          value: 'n',
          count: 55,
          example: 'no',
        },
        {
          value: 't',
          count: 56,
          example: 'tin',
        },
        {
          value: 'ɪ',
          count: 58,
          example: 'kit',
        },
        {
          value: 'ə',
          count: 78,
          example: 'comma',
        },
      ],
    },
    {
      key: 'pair',
      title: 'Phoneme pairs',
      covered: 382,
      inventory: null,
      units: [
        {
          value: 'aɪ k',
          count: 1,
          example: null,
        },
        {
          value: 'aɪ m',
          count: 1,
          example: null,
        },
        {
          value: 'aɪ s',
          count: 1,
          example: null,
        },
        {
          value: 'aɪ t',
          count: 1,
          example: null,
        },
        {
          value: 'aɪ v',
          count: 1,
          example: null,
        },
        {
          value: 'aʊ n',
          count: 1,
          example: null,
        },
        {
          value: 'aʊ t',
          count: 1,
          example: null,
        },
        {
          value: 'aʊ z',
          count: 1,
          example: null,
        },
        {
          value: 'b aɪ',
          count: 1,
          example: null,
        },
        {
          value: 'b aʊ',
          count: 1,
          example: null,
        },
        {
          value: 'b eɪ',
          count: 1,
          example: null,
        },
        {
          value: 'b j',
          count: 1,
          example: null,
        },
      ],
    },
    {
      key: 'stress',
      title: 'Stress patterns',
      covered: 12,
      inventory: null,
      units: [
        {
          value: '1000',
          count: 1,
          example: null,
        },
        {
          value: '101',
          count: 1,
          example: null,
        },
        {
          value: '102',
          count: 1,
          example: null,
        },
        {
          value: '11',
          count: 1,
          example: null,
        },
        {
          value: '1100',
          count: 1,
          example: null,
        },
        {
          value: '01',
          count: 2,
          example: null,
        },
        {
          value: '20',
          count: 2,
          example: null,
        },
        {
          value: '02',
          count: 3,
          example: null,
        },
        {
          value: '100',
          count: 3,
          example: null,
        },
        {
          value: '00',
          count: 6,
          example: null,
        },
        {
          value: '010',
          count: 7,
          example: null,
        },
        {
          value: '10',
          count: 47,
          example: null,
        },
      ],
    },
    {
      key: 'length',
      title: 'Lengths',
      covered: 2,
      inventory: 3,
      units: [
        {
          value: 'long',
          count: 0,
          example: null,
        },
        {
          value: 'short',
          count: 4,
          example: null,
        },
        {
          value: 'medium',
          count: 21,
          example: null,
        },
      ],
    },
    {
      key: 'sentence',
      title: 'Sentence types',
      covered: 4,
      inventory: 6,
      units: [
        {
          value: 'wh-question',
          count: 0,
          example: null,
        },
        {
          value: 'exclamation',
          count: 0,
          example: null,
        },
        {
          value: 'list',
          count: 1,
          example: null,
        },
        {
          value: 'several sentences',
          count: 2,
          example: null,
        },
        {
          value: 'yes/no question',
          count: 3,
          example: null,
        },
        {
          value: 'statement',
          count: 23,
          example: null,
        },
      ],
    },
    {
      key: 'style',
      title: 'Styles',
      covered: 5,
      inventory: 23,
      units: [
        {
          value: 'happy',
          count: 0,
          example: null,
        },
        {
          value: 'amused',
          count: 0,
          example: null,
        },
        {
          value: 'excited',
          count: 0,
          example: null,
        },
        {
          value: 'relaxed',
          count: 0,
          example: null,
        },
        {
          value: 'confident',
          count: 0,
          example: null,
        },
        {
          value: 'interested',
          count: 0,
          example: null,
        },
        {
          value: 'affectionate',
          count: 0,
          example: null,
        },
        {
          value: 'puzzled',
          count: 0,
          example: null,
        },
        {
          value: 'sad',
          count: 0,
          example: null,
        },
        {
          value: 'disappointed',
          count: 0,
          example: null,
        },
        {
          value: 'worried',
          count: 0,
          example: null,
        },
        {
          value: 'afraid',
          count: 0,
          example: null,
        },
        {
          value: 'annoyed',
          count: 0,
          example: null,
        },
        {
          value: 'angry',
          count: 0,
          example: null,
        },
        {
          value: 'bored',
          count: 0,
          example: null,
        },
        {
          value: 'tired',
          count: 0,
          example: null,
        },
        {
          value: 'sympathetic',
          count: 0,
          example: null,
        },
        {
          value: 'whispered',
          count: 0,
          example: null,
        },
        {
          value: 'pleased',
          count: 1,
          example: null,
        },
        {
          value: 'surprised',
          count: 1,
          example: null,
        },
        {
          value: 'sarcastic',
          count: 1,
          example: null,
        },
        {
          value: 'reassuring',
          count: 1,
          example: null,
        },
        {
          value: 'neutral',
          count: 21,
          example: null,
        },
      ],
    },
  ],
}
