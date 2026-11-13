import {QueryClient,QueryClientProvider} from '@tanstack/react-query';
import {render,screen} from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import {beforeEach,it,expect,vi} from 'vitest';
import {listCustomerTeam,saveCustomerTeam} from '../../api/customer-team.api';
import {CustomerTeamPanel} from './CustomerTeamPanel';
vi.mock('../../api/customer-team.api',()=>({listCustomerTeam:vi.fn(),saveCustomerTeam:vi.fn(),removeCustomerTeam:vi.fn()}));
const data={items:[],total:0,limit:20,offset:0,presets:[{code:'VIEW_ONLY',label:'View only',permissions:['profile.view']}],permissionCatalog:['profile.view','orders.view','inventory.view','notifications.view'],accounts:[{id:'owner',name:'Nishu Food',code:'R1',status:'APPROVED'},{id:'branch',name:'Delhi outlet',code:'R2',status:'APPROVED'}]};
beforeEach(()=>{vi.clearAllMocks();vi.mocked(listCustomerTeam).mockResolvedValue(data);vi.mocked(saveCustomerTeam).mockResolvedValue({} as never);});
function mount(canManage=true){render(<QueryClientProvider client={new QueryClient({defaultOptions:{queries:{retry:false}}})}><CustomerTeamPanel scope={{ownerId:'owner',merchantId:'m1',merchant:true}} canManage={canManage}/></QueryClientProvider>);}
it('creates direct account access from server presets without invitations',async()=>{
 mount();const user=userEvent.setup();await user.click(screen.getByRole('button',{name:'Manage team'}));await user.click(await screen.findByRole('button',{name:'Add team member'}));
 expect(screen.getByRole('checkbox',{name:'View inventory and movements'})).toBeInTheDocument();
 expect(screen.getByRole('checkbox',{name:'View notifications and mark read'})).toBeInTheDocument();
 await user.type(screen.getByLabelText(/Employee name/),'Rahul Employee');await user.type(screen.getByLabelText(/Employee mobile/),'9876543210');
 await user.selectOptions(screen.getAllByRole('combobox')[1],'branch');
 await user.click(screen.getByRole('button',{name:'Save team access'}));
 expect(saveCustomerTeam).toHaveBeenCalledWith(expect.anything(),expect.objectContaining({accountId:'branch',scopeType:'ACCOUNT',preset:'VIEW_ONLY',permissions:['profile.view']}),undefined);
 expect(screen.queryByRole('button',{name:/create invitation|manage login/i})).not.toBeInTheDocument();
});
it('read-only staff cannot add employees',async()=>{mount(false);await userEvent.click(screen.getByRole('button',{name:'Manage team'}));await screen.findByText(/No team members yet/);expect(screen.queryByRole('button',{name:'Add team member'})).not.toBeInTheDocument();});
