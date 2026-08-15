/// <reference types="vite/client" />

declare module "gbk.js" {
  interface GBKCodec {
    encode(value: string): number[];
    decode(value: ArrayLike<number>): string;
  }

  const GBK: GBKCodec;
  export default GBK;
}
