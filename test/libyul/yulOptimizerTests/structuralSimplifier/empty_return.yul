{
	return(memoryguard(0x80), 0)
}
// ----
// step: structuralSimplifier
//
// {
//     pop(memoryguard(0x80))
//     return(0, 0)
// }
