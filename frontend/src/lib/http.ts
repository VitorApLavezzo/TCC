/** O servidor respondeu e disse que o item não existe (e não: a rede caiu). */
export function isNotFound(err: any) {
  return err?.response?.status === 404;
}
